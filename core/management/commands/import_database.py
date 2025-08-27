from django.core.management.base import BaseCommand, CommandError
from pathlib import Path


class Command(BaseCommand):
    help = "Restore the PostgreSQL database from a backup file or the latest backup in backups directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backup-path",
            type=str,
            help="Absolute path to a .sql or .sql.gz backup file to restore",
        )
        parser.add_argument(
            "--backup-dir",
            type=str,
            help="Directory containing backups (default: <project_root>/backups)",
        )

    def handle(self, *args, **options):
        backup_path = options.get("backup_path")
        backup_dir = options.get("backup_dir")
        try:
            from core.tasks import restore_database

            # Run synchronously; Celery eager in tests
            result = restore_database.apply(args=[], kwargs={
                "backup_path": backup_path,
                "backup_dir": backup_dir,
            }).get()
            if result.get("status") == "success":
                self.stdout.write(self.style.SUCCESS(f"Database restored from: {result.get('path')}"))
            else:
                raise CommandError(result.get("error", "Unknown restore error"))
        except Exception as e:
            # Best-effort Telegram alert for system errors
            try:
                from core.utils.telegram import send_system_error_alert
                send_system_error_alert(f"Database restore failed (command): {e}")
            except Exception:
                pass
            raise CommandError(f"Database restore failed: {e}")


