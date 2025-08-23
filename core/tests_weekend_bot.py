from django.test import TestCase
from django.utils import timezone
import datetime as dt
from unittest.mock import patch

from .models import TradingConfig, ActivityLog
from .tasks import disable_bot_on_weekends


class WeekendDisableBotTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Test Config",
            is_active=True,
            bot_enabled=True,
            trading_enabled=True,
        )

    @patch("core.tasks.timezone")
    def test_disable_on_saturday(self, mock_tz):
        # Saturday (weekday=5)
        fake_now = dt.datetime(2025, 8, 23, 2, 45, 0, tzinfo=dt.timezone.utc)
        mock_tz.now.return_value = fake_now

        disable_bot_on_weekends()

        self.config.refresh_from_db()
        self.assertFalse(self.config.bot_enabled)
        self.assertTrue(
            ActivityLog.objects.filter(
                activity_type="system_event",
                message__icontains="disabled for weekend"
            ).exists()
        )

    @patch("core.tasks.timezone")
    def test_noop_on_weekday(self, mock_tz):
        # Monday (weekday=0)
        self.config.bot_enabled = True
        self.config.save(update_fields=["bot_enabled"])

        fake_now = dt.datetime(2025, 8, 25, 2, 45, 0, tzinfo=dt.timezone.utc)
        mock_tz.now.return_value = fake_now

        disable_bot_on_weekends()

        self.config.refresh_from_db()
        self.assertTrue(self.config.bot_enabled)
        self.assertFalse(
            ActivityLog.objects.filter(
                activity_type="system_event",
                message__icontains="Weekend check"
            ).exists()
        )


