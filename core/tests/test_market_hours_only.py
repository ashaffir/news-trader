from django.test import TestCase
from unittest.mock import patch

from core.models import TradingConfig, Source, Post, Analysis, Trade
from core.tasks import is_trading_allowed, create_new_trade


class MarketHoursOnlyEnforcementTests(TestCase):
    def setUp(self):
        # Active config; trading window is implicit market-hours-only via gate
        self.config = TradingConfig.objects.create(
            name="Test Config",
            is_active=True,
            bot_enabled=True,
        )

        # Minimal source/post/analysis to drive create_new_trade
        self.source = Source.objects.create(
            name="Test Source",
            url="https://example.com",
            scraping_enabled=False,
        )
        self.post = Post.objects.create(
            source=self.source,
            content="Test content",
            url="https://example.com/post/1",
        )
        self.analysis = Analysis.objects.create(
            post=self.post,
            symbol="AAPL",
            direction="buy",
            confidence=0.99,
            reason="Test",
        )

    @patch("core.tasks.is_market_open_broker_aware", return_value=False)
    def test_is_trading_allowed_blocks_when_market_closed(self, _mock_open):
        allowed, reason = is_trading_allowed()
        self.assertFalse(allowed)
        # Gate-based message contains mode; we only assert blocked
        self.assertFalse(allowed)

    @patch("core.tasks.is_market_open_broker_aware", return_value=False)
    def test_create_new_trade_aborts_when_market_closed(self, _mock_open):
        # Should not create a Trade when market is closed
        create_new_trade(self.analysis.id)
        self.assertEqual(Trade.objects.count(), 0)


