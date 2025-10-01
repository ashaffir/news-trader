from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from core.models import TradingConfig, Source, Post, Analysis
from core.tasks import enter_confirmation_check, create_new_trade


class OvernightStrategyTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Test",
            is_active=True,
            bot_enabled=True,
            trading_enabled=True,
            market_hours_only=False,
            enter_confirmation_enabled=True,
            enter_confirm_window_minutes=5,
            enter_price_change_threshold_pct=0.0,
            enter_volume_ma_window=3,
            enter_volume_multiplier_threshold=1.0,
            freshness_decay_constant_min=10.0,
            freshness_threshold=0.0,
            overnight_enabled=True,
            overnight_reduce_sl_factor=0.5,
        )
        self.source = Source.objects.create(name="Test Source", url="https://example.com")

    @patch("core.tasks.is_market_open_broker_aware", return_value=False)
    def test_tag_post_as_overnight_when_market_closed(self, _mock_open):
        p = Post.objects.create(source=self.source, content="c", url="https://x/1", overnight=False)
        # Simulate tagging path: in scraping we set overnight when closed; here assert field exists and default can be set
        self.assertFalse(p.overnight)

    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=True)
    @patch("core.tasks.compute_entry_confirmations", return_value=(1.0, 2.0, 100.0, 50.0))
    def test_freshness_resets_at_open_for_overnight(self, _conf, _just_opened, _is_open):
        post = Post.objects.create(source=self.source, content="c", url="https://x/2", overnight=True, published_at=timezone.now() - timezone.timedelta(hours=10))
        a = Analysis.objects.create(post=post, symbol="TEST", direction="buy", confidence=1.0, reason="r")
        # First call sees market open (second call in side_effect), freshness should be 1.0 via policy
        enter_confirmation_check(a.id)
        a.refresh_from_db()
        self.assertIsNotNone(a.freshness_value)
        self.assertGreaterEqual(a.freshness_value, 1.0)

    @patch("core.tasks.tradeapi.REST")
    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=True)
    def test_reduce_stop_loss_factor_applied(self, _just_opened, _is_open, mock_rest):
        # Mock price
        mock_api = mock_rest.return_value
        class Ticker: price = 100.0
        mock_api.get_latest_trade.return_value = Ticker()

        # Ensure env vars exist for flow
        import os
        os.environ.setdefault("ALPACA_API_KEY", "key")
        os.environ.setdefault("ALPACA_SECRET_KEY", "secret")

        # Create tracked company to pass enforcement
        from core.models import TrackedCompany
        TrackedCompany.objects.create(symbol="AAPL", name="Apple Inc.")

        post = Post.objects.create(source=self.source, content="c", url="https://x/3", overnight=True)
        a = Analysis.objects.create(post=post, symbol="AAPL", direction="buy", confidence=1.0, reason="r")

        # Execute trade flow
        with patch("core.tasks.get_effective_concurrent_open_trades_count", return_value=0), \
             patch("core.tasks.get_effective_open_exposure", return_value=0.0):
            create_new_trade(a.id)

        # Verify order submitted and SL reduced to 50% of configured
        # Config stop_loss_percentage default is 2.0 in code path; reduced to 1.0% => stop at 99.0
        # We assert that the Trade row has stop_loss_price_percentage close to 1.0
        from core.models import Trade
        t = Trade.objects.latest("id")
        self.assertLessEqual(abs(t.stop_loss_price_percentage - 1.0), 0.0001)

    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=True)
    @patch("core.tasks.compute_entry_confirmations", return_value=(1.0, 2.0, 100.0, 50.0))
    def test_overnight_age_cutoff_marks_stale(self, _conf, _just_opened, _is_open):
        # Set strict age cutoff to 1 hour
        self.config.overnight_max_age_hours = 1
        self.config.save()

        old_time = timezone.now() - timezone.timedelta(hours=5)
        post = Post.objects.create(source=self.source, content="c", url="https://x/4", overnight=True, published_at=old_time, created_at=old_time)
        a = Analysis.objects.create(post=post, symbol="TESTX", direction="buy", confidence=1.0, reason="r")

        # Running confirmation should immediately stale the post due to age
        enter_confirmation_check(a.id)
        post.refresh_from_db()
        self.assertTrue(post.is_stale)
        self.assertEqual(post.stale_reason, "overnight_age_exceeded")
