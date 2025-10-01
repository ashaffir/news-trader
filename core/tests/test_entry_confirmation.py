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

    @patch("trader.tasks.trades.create_new_trade.delay")
    @patch("core.tasks.check_daily_trade_limit", return_value=(True, ""))
    @patch("core.tasks.is_trading_allowed", return_value=(True, ""))
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_pass_opens_trade(self, mock_compute, _allowed, _daily, mock_create):
        # Price + volume pass
        mock_compute.return_value = (0.5, 2.0)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        mock_create.assert_called_once_with(a.id)

    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_fail_price(self, mock_compute, mock_update):
        mock_compute.return_value = (0.1, 2.0)  # price below 0.2
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        # Should not raise; should emit trade_rejected
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertIn("trade_rejected", types)

    @patch("core.tasks.send_dashboard_update")
    @patch("core.tasks.compute_entry_confirmations")
    def test_confirmation_fail_volume(self, mock_compute, mock_update):
        mock_compute.return_value = (1.0, 1.0)  # volume below 1.5
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
        mock_compute.return_value = (1.0, 2.0)
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
        mock_compute.return_value = (None, None)
        a = self._make_analysis("buy")
        enter_confirmation_check(a.id)
        types = [c.args[0] for c in mock_update.call_args_list]
        self.assertIn("trade_rejected", types)


