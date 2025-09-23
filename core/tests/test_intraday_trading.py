from django.test import TestCase
from unittest.mock import patch

from core.models import TradingConfig, ActivityLog
from core.tasks import enforce_intraday_preclose


class IntradayTradingTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Intraday",
            is_active=True,
            trading_enabled=True,
            bot_enabled=True,
            intraday_trading=True,
            intraday_close_minutes_before=30,
        )

    @patch("core.tasks.close_all_trades_manually.delay")
    @patch("core.tasks.minutes_until_market_close", return_value=25)
    def test_dispatches_preclose_within_threshold(self, _mock_minutes, mock_close):
        result = enforce_intraday_preclose()
        mock_close.assert_called_once()
        self.assertEqual(result.get("status"), "dispatched")
        self.assertTrue(ActivityLog.objects.filter(message__icontains="Intraday pre-close").exists())

    @patch("core.tasks.close_all_trades_manually.delay")
    @patch("core.tasks.minutes_until_market_close", return_value=45)
    def test_noop_when_outside_threshold(self, _mock_minutes, mock_close):
        result = enforce_intraday_preclose()
        mock_close.assert_not_called()
        self.assertEqual(result.get("status"), "noop")


