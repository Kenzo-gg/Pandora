"""Windows-user encrypted MySQL snapshots, isolated restore verification and live restore."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import pickle
import re
from uuid import uuid4

import MySQLdb
from django.db import connection

from .reports import MANILA

DAILY_PATTERN = 'pandora-????-??-??.dpapi'
SAFETY_PATTERN = 'pre-restore-*.dpapi'


class BackupBusy(Exception):
    """Another backup or restore holds the lock."""


class RestoreError(Exception):
    """A live restore failed; `entry` says whether the live database was changed."""

    def __init__(self, entry):
        super().__init__(entry.get('error_type', 'RestoreError'))
        self.entry = entry


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, *, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def quoted(name):
    return '`' + name.replace('`', '``') + '`'


def rows_digest(rows):
    return hashlib.sha256(pickle.dumps(tuple(sorted(rows, key=repr)), protocol=4)).hexdigest()


def snapshot():
    params = connection.get_connection_params()
    source = MySQLdb.connect(**params)
    try:
        with source.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cursor.execute('SELECT TABLE_NAME, ENGINE, TABLE_TYPE FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME')
            tables = cursor.fetchall()
            if not tables or any(engine != 'InnoDB' or kind != 'BASE TABLE' for _, engine, kind in tables):
                raise ValueError('Backup requires InnoDB base tables.')
            result = {}
            for table, _, _ in tables:
                cursor.execute('SHOW CREATE TABLE ' + quoted(table))
                ddl = cursor.fetchone()[1]
                cursor.execute('SELECT * FROM ' + quoted(table))
                rows = cursor.fetchall()
                columns = [column[0] for column in cursor.description]
                result[table] = {'ddl': ddl, 'columns': columns, 'rows': rows,
                                 'digest': rows_digest(rows)}
            source.commit()
            return result
    finally:
        source.close()


def write_backup(path, data):
    Path(path).write_bytes(protect(pickle.dumps(data, protocol=4)))


def read_backup(path):
    # Only consume backups created by this application in the protected directory.
    # Pickle data is authenticated by the current-user DPAPI envelope before loading.
    return pickle.loads(protect(Path(path).read_bytes(), decrypt=True))


def load_tables(cursor, data):
    """Create every table in the cursor's current database and insert its rows."""
    cursor.execute('SET FOREIGN_KEY_CHECKS=0')
    for table in data.values():
        cursor.execute(table['ddl'])
    for name, table in data.items():
        if table['rows']:
            columns = ','.join(quoted(column) for column in table['columns'])
            placeholders = ','.join(['%s'] * len(table['columns']))
            cursor.executemany(f'INSERT INTO {quoted(name)} ({columns}) VALUES ({placeholders})', table['rows'])
    cursor.execute('SET FOREIGN_KEY_CHECKS=1')


def check_tables(cursor, data):
    """Compare every loaded table with the snapshot's row fingerprint."""
    results = {}
    for name, table in data.items():
        cursor.execute('SELECT * FROM ' + quoted(name))
        restored = cursor.fetchall()
        if rows_digest(restored) != table['digest']:
            raise ValueError('Restored table does not match snapshot.')
        results[name] = {'rows': len(restored), 'sha256': table['digest']}
    return results


def verify_data(data):
    params = connection.get_connection_params()
    params.pop('db', None)
    params.pop('database', None)
    target = 'pandora_recovery_' + uuid4().hex
    server = MySQLdb.connect(**params)
    created = False
    try:
        with server.cursor() as cursor:
            # CREATE without IF NOT EXISTS prevents any reuse of an existing database.
            cursor.execute('CREATE DATABASE ' + quoted(target) + ' CHARACTER SET utf8mb4')
            created = True
            cursor.execute('USE ' + quoted(target))
            load_tables(cursor, data)
            server.commit()
            results = check_tables(cursor, data)
            return {'target': target, 'all_tables_match': True, 'tables': results,
                    'target_removed_after_check': True}
    finally:
        if created:
            # Only the fresh UUID database created in this invocation can be removed.
            if not re.fullmatch(r'pandora_recovery_[a-f0-9]{32}', target):
                raise ValueError('Invalid recovery target.')
            with server.cursor() as cursor:
                cursor.execute('DROP DATABASE ' + quoted(target))
        server.close()


def restore_verify(path):
    return verify_data(read_backup(path))


def replace_live(data):
    """Drop every table in the configured database, then load and check `data`."""
    live = MySQLdb.connect(**connection.get_connection_params())
    try:
        with live.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            cursor.execute("SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
            existing = [row[0] for row in cursor.fetchall()]
            if existing:
                cursor.execute('DROP TABLE ' + ','.join(quoted(name) for name in existing))
            load_tables(cursor, data)
            live.commit()
            return check_tables(cursor, data)
    finally:
        live.close()


def default_directory():
    return Path(os.environ['LOCALAPPDATA']) / 'Pandora' / 'Backups'


def list_backups(directory):
    """Daily and pre-restore backups in `directory`, newest first."""
    directory = Path(directory)
    found = list(directory.glob(DAILY_PATTERN)) + list(directory.glob(SAFETY_PATTERN))
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def find_backup(directory, choice):
    """Resolve 'latest', a YYYY-MM-DD date, or a listed file name to a backup in `directory`."""
    if choice == 'latest':
        daily = sorted(Path(directory).glob(DAILY_PATTERN), reverse=True)
        return daily[0] if daily else None
    wanted = {choice, f'pandora-{choice}.dpapi'}
    # Matching listed names only means no path outside the backup directory is ever read.
    return next((path for path in list_backups(directory) if path.name in wanted), None)


def append_log(directory, entry):
    with (Path(directory) / 'backup-log.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps(entry) + '\n')


@contextmanager
def exclusive(directory):
    """Hold the backup lock; yields False if another backup or restore has it."""
    import msvcrt

    with (Path(directory) / 'backup.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def run_backup(directory, *, verify=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(MANILA)
    entry = {'time': now.isoformat(), 'status': 'failed'}
    with exclusive(directory) as acquired:
        if not acquired:
            entry['status'] = 'skipped_busy'
            append_log(directory, entry)
            return entry
        temporary = directory / 'backup.pending'
        try:
            data = snapshot()
            write_backup(temporary, data)
            verification = restore_verify(temporary) if verify else None
            path = directory / f'pandora-{now:%Y-%m-%d}.dpapi'
            temporary.replace(path)
            entry.update(status='success', file=path.name, bytes=path.stat().st_size,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest(), tables=len(data))
            if verification:
                entry['verification'] = verification
            # Retain seven successful daily snapshots. Failed attempts never prune.
            backups = sorted(directory.glob(DAILY_PATTERN), reverse=True)
            for old in backups[7:]:
                old.unlink()
            return entry
        except Exception as exc:
            # Record the error class without credentials or SQL data in logs.
            entry['error_type'] = type(exc).__name__
            raise
        finally:
            temporary.unlink(missing_ok=True)
            append_log(directory, entry)


def restore_live(path, directory):
    """Replace the live database with the backup at `path`.

    The backup is first proven in an isolated database, and the current data is saved
    as a pre-restore backup. If loading into the live database fails, the saved data
    is loaded back automatically.
    """
    directory = Path(directory)
    path = Path(path)
    now = datetime.now(MANILA)
    entry = {'time': now.isoformat(), 'action': 'restore', 'file': path.name, 'status': 'failed'}
    with exclusive(directory) as acquired:
        if not acquired:
            entry['status'] = 'skipped_busy'
            append_log(directory, entry)
            raise BackupBusy()
        try:
            data = read_backup(path)
            verify_data(data)
            current = snapshot()
            safety = directory / f'pre-restore-{now:%Y-%m-%d-%H%M%S}.dpapi'
            write_backup(safety, current)
            entry['safety_backup'] = safety.name
            try:
                tables = replace_live(data)
            except Exception:
                entry['rolled_back'] = False
                replace_live(current)
                entry['rolled_back'] = True
                raise
            entry.update(status='success', tables=len(tables),
                         rows=sum(table['rows'] for table in tables.values()))
            return entry
        except Exception as exc:
            # Record the error class without credentials or SQL data in logs.
            entry['error_type'] = type(exc).__name__
            raise RestoreError(entry) from exc
        finally:
            append_log(directory, entry)
