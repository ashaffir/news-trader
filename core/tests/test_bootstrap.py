from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from core.models import TradingConfig, AlertSettings, Source


class BootstrapCommandTests(TestCase):
    def test_bootstrap_full_setup_creates_everything(self):
        call_command(
            "bootstrap_full_setup",
            "--superuser",
            "alfreds",
            "--password",
            "!Q2w3e4r%T",
            "--email",
            "admin@example.com",
            "--with-cnbc-latest",
        )

        User = get_user_model()
        self.assertTrue(User.objects.filter(username="alfreds", is_superuser=True).exists())

        # Trading config
        config = TradingConfig.objects.filter(name="Default Trading Configuration").first()
        self.assertIsNotNone(config)
        self.assertTrue(config.is_active)
        # Bot should start disabled by default
        self.assertFalse(config.bot_enabled)
        self.assertTrue(config.trading_enabled)

        # Alert settings
        self.assertTrue(AlertSettings.objects.exists())

        # CNBC source
        self.assertTrue(Source.objects.filter(url="https://www.cnbc.com/latest/").exists())



