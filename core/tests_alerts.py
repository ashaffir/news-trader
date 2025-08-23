from django.test import TestCase
from unittest.mock import patch

from core.models import AlertSettings
from core.utils.telegram import is_alert_enabled, send_system_error_alert


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


