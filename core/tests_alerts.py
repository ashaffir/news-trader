from django.test import TestCase
from unittest.mock import patch

from core.models import AlertSettings
from core.utils.telegram import is_alert_enabled, send_system_error_alert
from core.tasks import send_dashboard_update


class AlertSettingsTests(TestCase):
    def test_is_alert_enabled_system_error_toggle(self):
        AlertSettings.objects.create(
            enabled=True,
            system_errors_enabled=True,
        )
        self.assertTrue(is_alert_enabled("system_error"))

        # Global disable should override
        AlertSettings.objects.create(
            enabled=False,
            system_errors_enabled=True,
        )
        self.assertFalse(is_alert_enabled("system_error"))

    @patch("core.utils.telegram.send_telegram_message")
    def test_send_system_error_alert_respects_toggle(self, mock_send):
        # Enabled -> should send
        AlertSettings.objects.create(
            enabled=True,
            system_errors_enabled=True,
        )
        mock_send.return_value = True
        ok = send_system_error_alert("Something bad happened")
        self.assertTrue(ok)
        mock_send.assert_called_once()

        # Disabled -> should not send
        AlertSettings.objects.create(
            enabled=False,
            system_errors_enabled=True,
        )
        mock_send.reset_mock()
        ok2 = send_system_error_alert("Another error")
        self.assertFalse(ok2)
        mock_send.assert_not_called()


class TelegramAlertSuppressionTests(TestCase):
    @patch("core.utils.telegram.send_telegram_message")
    def test_suppress_alerts_with_na_content_for_trading_types(self, mock_send):
        AlertSettings.objects.create(
            enabled=True,
            order_open_enabled=True,
            order_close_enabled=True,
            trading_limit_enabled=True,
        )

        # new_trade mapped to order_open_enabled; message contains N/A via formatting
        send_dashboard_update(
            "new_trade",
            {
                "trade_id": 1,
                "symbol": None,  # triggers 'N/A' in formatted message
                "direction": "buy",
                "quantity": 10,
                "status": "pending",
                "entry_price": 100.0,
                "stop_loss_price": 98.0,
                "take_profit_price": 110.0,
            },
        )

        mock_send.assert_not_called()

    @patch("core.utils.telegram.send_telegram_message")
    def test_does_not_suppress_non_na_messages(self, mock_send):
        AlertSettings.objects.create(
            enabled=True,
            order_open_enabled=True,
        )

        mock_send.return_value = True

        send_dashboard_update(
            "new_trade",
            {
                "trade_id": 2,
                "symbol": "AAPL",
                "direction": "buy",
                "quantity": 5,
                "status": "pending",
                "entry_price": 190.0,
                "stop_loss_price": 180.0,
                "take_profit_price": 210.0,
            },
        )

        mock_send.assert_called_once()

