from django.test import TestCase
from django.core.management import call_command
from unittest.mock import patch, MagicMock
from pathlib import Path
from django.urls import reverse


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
    @patch("core.utils.db_backup._resolve_pg_dump_path", return_value="/usr/bin/pg_dump")
    @patch("core.utils.db_backup.subprocess.run")
    def test_create_database_backup_invokes_pg_dump(self, mock_run, mock_resolve):
        from core.utils import db_backup
        temp_dir = Path("/tmp/news_trader_test_backups")
        try:
            if temp_dir.exists():
                # Clean any previous leftovers
                for p in temp_dir.glob("*"):
                    p.unlink()
            else:
                temp_dir.mkdir(parents=True, exist_ok=True)

            # When pg_dump is called, create the temp .sql file passed after '-f'
            def _side_effect(cmd, check=True, env=None):
                if "-f" in cmd:
                    out_idx = cmd.index("-f") + 1
                    temp_sql = Path(cmd[out_idx])
                    temp_sql.write_text("-- dummy sql")
                return MagicMock()
            mock_run.side_effect = _side_effect

            backup_path = db_backup.create_database_backup(temp_dir)

            # Ensure pg_dump was invoked
            self.assertTrue(mock_run.called)
            args, kwargs = mock_run.call_args
            cmd = args[0]
            # Verify '-f' argument contains our computed path
            self.assertIn("-f", cmd)
            # '-f' should point to the intermediate .sql file, not the final .gz
            f_path = cmd[cmd.index("-f") + 1]
            self.assertTrue(str(f_path).endswith('.sql'))
            # Verify final gzip extension returned
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


class BackupAPITests(TestCase):
    @patch("core.tasks.ActivityLog.objects.create")
    @patch("core.utils.db_backup.create_database_backup")
    def test_trigger_backup_api(self, mock_create_backup, mock_log_create):
        # Create staff user and login
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user("admin", is_staff=True))

        mock_create_backup.return_value = Path("/tmp/fake_backup.sql.gz")

        resp = self.client.post(reverse("api_trigger_backup"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("path", data)

    @patch("core.utils.telegram.send_system_error_alert")
    @patch("core.tasks.ActivityLog.objects.create")
    @patch("core.utils.db_backup.create_database_backup")
    def test_backup_task_failure_sends_alert(self, mock_create_backup, mock_log_create, mock_alert):
        from core.tasks import backup_database

        mock_create_backup.side_effect = RuntimeError("pg_dump not found")
        result = backup_database()

        self.assertEqual(result["status"], "error")
        mock_alert.assert_called_once()


