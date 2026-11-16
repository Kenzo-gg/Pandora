"""Windows-user encrypted MySQL snapshots and isolated restore verification."""
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


def restore_verify(path):
    # Only consume backups created by this application in the protected directory.
    # Pickle data is authenticated by the current-user DPAPI envelope before loading.
    data = pickle.loads(protect(Path(path).read_bytes(), decrypt=True))
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
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            for table in data.values():
                cursor.execute(table['ddl'])
            for name, table in data.items():
                if table['rows']:
                    columns = ','.join(quoted(column) for column in table['columns'])
                    placeholders = ','.join(['%s'] * len(table['columns']))
                    cursor.executemany(f'INSERT INTO {quoted(name)} ({columns}) VALUES ({placeholders})', table['rows'])
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')
            server.commit()
            results = {}
            for name, table in data.items():
                cursor.execute('SELECT * FROM ' + quoted(name))
                restored = cursor.fetchall()
                if rows_digest(restored) != table['digest']:
                    raise ValueError('Restored table does not match snapshot.')
                results[name] = {'rows': len(restored), 'sha256': table['digest']}
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


def default_directory():
    return Path(os.environ['LOCALAPPDATA']) / 'Pandora' / 'Backups'


def run_backup(directory, *, verify=False):
    import msvcrt

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / 'backup-log.jsonl'
    now = datetime.now(MANILA)
    entry = {'time': now.isoformat(), 'status': 'failed'}
    with (directory / 'backup.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            entry['status'] = 'skipped_busy'
            with log.open('a', encoding='utf-8') as output:
                output.write(json.dumps(entry) + '\n')
            return entry
        temporary = directory / 'backup.pending'
        try:
            data = snapshot()
            temporary.write_bytes(protect(pickle.dumps(data, protocol=4)))
            verification = restore_verify(temporary) if verify else None
            path = directory / f'pandora-{now:%Y-%m-%d}.dpapi'
            temporary.replace(path)
            entry.update(status='success', file=path.name, bytes=path.stat().st_size,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest(), tables=len(data))
            if verification:
                entry['verification'] = verification
            # Retain seven successful daily snapshots. Failed attempts never prune.
            backups = sorted(directory.glob('pandora-????-??-??.dpapi'), reverse=True)
            for old in backups[7:]:
                old.unlink()
            return entry
        except Exception as exc:
            # Record the error class without credentials or SQL data in logs.
            entry['error_type'] = type(exc).__name__
            raise
        finally:
            temporary.unlink(missing_ok=True)
            with log.open('a', encoding='utf-8') as output:
                output.write(json.dumps(entry) + '\n')
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
