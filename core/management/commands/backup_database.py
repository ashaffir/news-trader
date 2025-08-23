from django.core.management.base import BaseCommand, CommandError
from pathlib import Path


class Command(BaseCommand):
    help = "Create a local compressed PostgreSQL database backup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            help="Directory to store the backup file (default: <project_root>/backups)",
        )

    def handle(self, *args, **options):
        output_dir = options.get("output_dir")
        try:
            from core.utils.db_backup import (
                create_database_backup,
                get_default_backup_dir,
            )

            target_dir = Path(output_dir) if output_dir else get_default_backup_dir()
            backup_path = create_database_backup(target_dir)
            self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_path}"))
        except Exception as e:
            # Best-effort Telegram alert for system errors
            try:
                from core.utils.telegram import send_system_error_alert
                send_system_error_alert(f"Database backup failed (command): {e}")
            except Exception:
                pass
            raise CommandError(f"Database backup failed: {e}")


