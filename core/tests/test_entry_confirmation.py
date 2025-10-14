from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from core.models import Source, Post, Analysis, TradingConfig, TrackedCompany
from core.tasks import enter_confirmation_check
from core.models import TradeLifecycleEvent


class EntryConfirmationTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Test Config",
            is_active=True,
            bot_enabled=True,
            min_confidence_threshold=0.5,
            enter_confirmation_enabled=True,
            enter_confirm_window_minutes=5,
            enter_price_change_threshold_pct=0.2,
            enter_volume_ma_window=20,
            enter_volume_multiplier_threshold=1.5,
            freshness_decay_constant_min=10.0,
            freshness_threshold=0.5,
        )
        TrackedCompany.objects.get_or_create(symbol="AAPL", defaults={"name": "Apple"})
        self.source = Source.objects.create(name="S", url="https://x/1")
        self.post = Post.objects.create(source=self.source, content="AAPL news", url="https://x/1/p")

    def _make_analysis(self, direction="buy"):
        return Analysis.objects.create(
            post=self.post,
            symbol="AAPL",
            direction=direction,
            confidence=0.9,
            reason="test",
            trading_config_used=self.config,
            created_at=timezone.now(),
        )

    @patch("core.tasks.create_new_trade.run")
    @patch("trader.tasks.trades.create_new_trade.run")
    @patch("core.tasks.check_daily_trade_limit", return_value=(True, ""))
    @patch("core.tasks.is_trading_allowed", return_value=(True, ""))
    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=False)
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_pass_opens_trade(self, mock_compute, _open_now, _just_opened, _allowed, _daily, _run_trader, _run_core):
        # Price + volume pass
        mock_compute.return_value = (0.5, 2.0, 1000.0, 500.0)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        a.refresh_from_db()
        self.assertTrue(a.enter_confirmed)
        self.assertEqual(a.enter_status, "confirm_passed")

    @patch("core.tasks.create_new_trade.run")
    @patch("trader.tasks.trades.create_new_trade.run")
    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.is_trading_allowed", return_value=(True, ""))
    @patch("core.tasks.check_daily_trade_limit", return_value=(True, ""))
    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=False)
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_pass_with_volume_only(self, mock_compute, _just_opened, _open_now, _daily, _allowed, mock_update, _run_trader, _run_core):
        # Price below threshold but volume above: should PASS due to OR
        mock_compute.return_value = (0.1, 2.0, 1000.0, 500.0)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        # Should not emit rejection; no trade_rejected call
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertNotIn("trade_rejected", types)

    @patch("core.tasks.create_new_trade.run")
    @patch("trader.tasks.trades.create_new_trade.run")
    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.is_trading_allowed", return_value=(True, ""))
    @patch("core.tasks.check_daily_trade_limit", return_value=(True, ""))
    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=False)
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_pass_with_price_only(self, mock_compute, _just_opened, _open_now, _daily, _allowed, mock_update, _run_trader, _run_core):
        # Price above threshold but volume below: should PASS due to OR
        mock_compute.return_value = (0.5, 1.0, 1000.0, 2000.0)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertNotIn("trade_rejected", types)

    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.is_market_open_broker_aware", return_value=True)
    @patch("core.tasks.market_just_opened", return_value=False)
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_fail_both(self, mock_compute, _just_opened, _open_now, mock_update):
        mock_compute.return_value = (0.0, 1.0, 100.0, 200.0)  # both below
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertIn("trade_rejected", types)
        # lifecycle event should capture failure
        self.assertTrue(TradeLifecycleEvent.objects.filter(subject_type="analysis", subject_id=a.id, event_type="entry_confirm_failed").exists())

    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.compute_entry_confirmations")
    def test_freshness_fail(self, mock_compute, mock_update):
        # Simulate old publication
        mock_compute.return_value = (1.0, 2.0, 1000.0, 500.0)
        a = self._make_analysis("buy")
        # set published_at far in the past to make freshness drop
        a.post.published_at = timezone.now() - timezone.timedelta(minutes=120)
        a.post.save(update_fields=["published_at"])
        enter_confirmation_check(a.id)
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertIn("trade_rejected", types)

    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.compute_entry_confirmations")
    def test_no_data_reject(self, mock_compute, mock_update):
        mock_compute.return_value = (None, None, None, None)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertIn("trade_rejected", types)


