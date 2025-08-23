import os
import time
import tempfile
from pathlib import Path

from django.test import TestCase


class LogCleanupTests(TestCase):
    def test_cleanup_logs_deletes_old_files(self):
        from core.utils.logs import cleanup_logs

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            keep_file = log_dir / "django.log"
            old_file = log_dir / "django.log.1"

            keep_file.write_text("recent log")
            old_file.write_text("old log")

            now = time.time()
            forty_days = 40 * 24 * 3600
            os.utime(keep_file, (now, now))
            os.utime(old_file, (now - forty_days, now - forty_days))

            result = cleanup_logs(log_dir, max_age_days=30)

            assert result["deleted_count"] == 1
            assert keep_file.exists()
            assert not old_file.exists()

    def test_logging_rotation_config_applied(self):
        import logging
        import logging.config
        import importlib
        import os as _os

        # Force retention to 3 for this test and reload base settings module
        old_val = _os.getenv("LOG_RETENTION_DAYS")
        _os.environ["LOG_RETENTION_DAYS"] = "3"
        try:
            from news_trader import settings as base_settings
            importlib.reload(base_settings)

            logging.config.dictConfig(base_settings.LOGGING)
            root_logger = logging.getLogger()
            file_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.handlers.TimedRotatingFileHandler)
            ]
            assert file_handlers, "TimedRotatingFileHandler should be configured"
            fh = file_handlers[0]
            # backupCount equals retention days
            assert fh.backupCount == 3
            # Rotates at midnight
            assert getattr(fh, 'when', '').upper() == 'MIDNIGHT'
        finally:
            # restore env
            if old_val is None:
                _os.environ.pop("LOG_RETENTION_DAYS", None)
            else:
                _os.environ["LOG_RETENTION_DAYS"] = old_val


