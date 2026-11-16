from django.core.management.base import BaseCommand, CommandError
from pandoraapp.backup_tools import default_directory, run_backup
import json


class Command(BaseCommand):
    help = 'Create an encrypted current-user Windows backup, retaining seven daily copies.'

    def add_arguments(self, parser):
        parser.add_argument('--verify-restore', action='store_true', help='Restore to a fresh isolated schema, compare all tables, then remove that schema.')

    def handle(self, *args, **options):
        try:
            result = run_backup(default_directory(), verify=options['verify_restore'])
        except Exception as exc:
            raise CommandError('Backup failed (' + type(exc).__name__ + '). Check backup-log.jsonl and MySQL availability.') from None
        self.stdout.write(json.dumps(result, indent=2))
