from django.test import TestCase
from django.utils import timezone
import datetime as dt
from unittest.mock import patch

from core.models import TradingConfig, ActivityLog
from core.tasks import disable_bot_on_weekends, weekend_shutoff


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


class WeekendShutoffTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Test Config",
            is_active=True,
            bot_enabled=True,
            trading_enabled=True,
        )

    @patch("core.tasks.close_all_trades_manually")
    def test_weekend_shutoff_disables_bot_and_dispatches_close(self, mock_close_all):
        # Ensure bot starts enabled
        self.config.bot_enabled = True
        self.config.save(update_fields=["bot_enabled"])

        result = weekend_shutoff()

        # Close-all was dispatched
        mock_close_all.delay.assert_called_once()

        # Bot disabled
        self.config.refresh_from_db()
        self.assertFalse(self.config.bot_enabled)

        # Activity logged
        self.assertTrue(
            ActivityLog.objects.filter(
                activity_type="system_event",
                message__icontains="Weekend shutoff"
            ).exists()
        )

        # Summary keys present
        self.assertIn("close_all_dispatched", result)
        self.assertIn("bot_disabled", result)

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


