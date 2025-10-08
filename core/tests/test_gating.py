from django.test import TestCase
from django.utils import timezone
from core.models import TradingConfig
from core.utils.gating import get_gate


class GateFunctionTests(TestCase):
    def setUp(self):
        TradingConfig.objects.create(
            name="Test",
            is_active=True,
            bot_enabled=True,
            autostart=False,
            overnight_enabled=True,
        )

    def test_manual_test_never_trades(self):
        gate = get_gate(manual_test=True)
        self.assertTrue(gate["allow_scrape"])  # bypass
        self.assertFalse(gate["allow_trading"])  # never allow trades in manual

    def test_weekend_allows_overnight_blocks_trading(self):
        # Force a weekend by mocking timezone.now
        class DummyTZ:
            @staticmethod
            def now():
                # Saturday 14:00 UTC
                return timezone.datetime(2025, 1, 4, 14, 0, 0, tzinfo=timezone.utc)

        orig = timezone.now
        timezone.now = DummyTZ.now
        try:
            gate = get_gate(manual_test=False)
            self.assertTrue(gate["allow_overnight_collection"])  # weekend overnight OK
            self.assertFalse(gate["allow_trading"])  # no trading on weekends
        finally:
            timezone.now = orig


