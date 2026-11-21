from datetime import datetime
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from pandoraapp.backup_tools import (BackupBusy, RestoreError, default_directory, find_backup,
                                     list_backups, restore_live)


class Command(BaseCommand):
    help = ('Replace the live database with an encrypted backup. Run with no arguments to list '
            'the backups you can restore.')

    def add_arguments(self, parser):
        parser.add_argument('backup', nargs='?',
            help='"latest", a date such as 2026-11-21, or a file name from the list.')
        parser.add_argument('--yes', action='store_true',
            help='Skip the confirmation prompt.')

    def handle(self, *args, **options):
        directory = default_directory()
        if not options['backup']:
            return self.show_list(directory)

        path = find_backup(directory, options['backup'])
        if path is None:
            raise CommandError(f'No backup matches "{options["backup"]}". '
                               'Run restore_pandora with no arguments to see the list.')

        database = connection.settings_dict['NAME']
        if not options['yes']:
            if not sys.stdin.isatty():
                raise CommandError('Add --yes to restore without a confirmation prompt.')
            self.stdout.write(self.style.WARNING(
                f'This replaces every table in the "{database}" database with {path.name}.\n'
                'Stop the Pandora server first. The current data is saved as a '
                'pre-restore backup before anything changes.'))
            if input(f'Type {database} to continue: ').strip() != database:
                raise CommandError('Restore cancelled. Nothing was changed.')

        try:
            result = restore_live(path, directory)
        except BackupBusy:
            raise CommandError('A backup or restore is already running. Try again when it finishes.') from None
        except RestoreError as error:
            entry = error.entry
            message = f'Restore failed ({entry.get("error_type")}). '
            if entry.get('rolled_back'):
                message += 'The live database was put back the way it was.'
            elif 'rolled_back' in entry:
                message += ('Putting the old data back also failed. Restore it with: '
                            f'manage.py restore_pandora {entry["safety_backup"]}')
            else:
                message += 'The live database was not changed.'
            raise CommandError(message + ' Details are in backup-log.jsonl.') from None

        self.stdout.write(self.style.SUCCESS(
            f'Restored {result["file"]}: {result["tables"]} tables, {result["rows"]} rows, '
            'all matching the backup.'))
        self.stdout.write(f'The data from before the restore is saved as {result["safety_backup"]}.')
        self.stdout.write('If the backup is from an older version of Pandora, run manage.py migrate next.')

    def show_list(self, directory):
        backups = list_backups(directory)
        if not backups:
            self.stdout.write(f'No backups found in {directory}.')
            return
        self.stdout.write(f'Backups in {directory} (newest first):')
        for path in backups:
            info = path.stat()
            saved = datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M')
            self.stdout.write(f'  {path.name:<40} {saved}  {info.st_size / 1024:,.0f} KB')
        self.stdout.write('Restore one with: manage.py restore_pandora <name, date or latest>')
