from django.test import TestCase
from django.core.management import call_command
from unittest.mock import patch, MagicMock
from pathlib import Path


class BackupPeriodicTaskTests(TestCase):
    def test_setup_registers_backup_crontab_task(self):
        # Ensure crontab is created and periodic task is registered
        from django_celery_beat.models import PeriodicTask

        # Run setup command
        call_command("setup_periodic_tasks")

        # Verify backup task exists
        self.assertTrue(
            PeriodicTask.objects.filter(name="Daily Database Backup (Local)").exists()
        )
        task = PeriodicTask.objects.get(name="Daily Database Backup (Local)")
        self.assertIsNotNone(task.crontab)
        self.assertEqual(task.task, "core.tasks.backup_database")


class BackupUtilityTests(TestCase):
    @patch("core.utils.db_backup.subprocess.run")
    def test_create_database_backup_invokes_pg_dump(self, mock_run):
        from core.utils import db_backup
        temp_dir = Path("/tmp/news_trader_test_backups")
        try:
            if temp_dir.exists():
                # Clean any previous leftovers
                for p in temp_dir.glob("*"):
                    p.unlink()
            else:
                temp_dir.mkdir(parents=True, exist_ok=True)

            backup_path = db_backup.create_database_backup(temp_dir)

            # Ensure pg_dump was invoked
            self.assertTrue(mock_run.called)
            args, kwargs = mock_run.call_args
            cmd = args[0]
            # Verify '-f' argument contains our computed path
            self.assertIn("-f", cmd)
            self.assertIn(str(backup_path), cmd)
            # Verify gzip extension
            self.assertTrue(str(backup_path).endswith(".sql.gz"))
        finally:
            # Clean up temp dir
            if temp_dir.exists():
                for p in temp_dir.glob("*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass


class BackupTaskTests(TestCase):
    @patch("core.tasks.ActivityLog.objects.create")
    @patch("core.utils.db_backup.create_database_backup")
    def test_backup_task_success(self, mock_create_backup, mock_log_create):
        from core.tasks import backup_database

        mock_create_backup.return_value = Path("/tmp/fake_backup.sql.gz")
        result = backup_database()

        self.assertEqual(result["status"], "success")
        self.assertIn("path", result)
        mock_create_backup.assert_called_once()
        self.assertTrue(mock_log_create.called)


