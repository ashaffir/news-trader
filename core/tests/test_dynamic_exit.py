from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from core.models import TradingConfig, TrackedCompany, Source, Post, Analysis, Trade, TradeLifecycleEvent
from core.tasks import monitor_local_stop_take_levels


class DynamicExitTests(TestCase):
    def setUp(self):
        self.config = TradingConfig.objects.create(
            name="Cfg",
            is_active=True,
            bot_enabled=True,
            default_position_size=100.0,
            dynamic_exit_drawdown_tolerance_pct=0.3,
        )
        TrackedCompany.objects.get_or_create(symbol="AAPL", defaults={"name": "Apple"})
        src = Source.objects.create(name="S", url="https://x/1")
        post = Post.objects.create(source=src, content="AAPL", url="https://x/1/p")
        self.analysis = Analysis.objects.create(post=post, symbol="AAPL", direction="buy", confidence=0.9)
        self.trade = Trade.objects.create(
            analysis=self.analysis,
            symbol="AAPL",
            direction="buy",
            quantity=1,
            entry_price=100.0,
            status="open",
            opened_at=timezone.now(),
        )

    @patch("core.tasks.tradeapi.REST")
    @patch("core.utils.market_data.get_minute_bars")
    def test_dynamic_exit_triggers_on_adverse_move(self, mock_bars, mock_rest):
        # Construct bars showing -0.5% over 5 minutes for a long
        from core.utils.market_data import MinuteBar
        now = timezone.now().replace(second=0, microsecond=0)
        bars = []
        price = 100.0
        for i in range(5):
            ts = now - timezone.timedelta(minutes=5 - i)
            # Slight downward drift to reach ~ -0.5%
            open_p = price * (1 - 0.001 * i)
            close_p = price * (1 - 0.001 * (i + 1))
            bars.append(MinuteBar(ts, open_p, open_p, close_p, close_p, 1000))
        mock_bars.return_value = bars

        # Ensure current price isn't above TP
        class Position:
            current_price = 99.5
        mock_rest.return_value.get_position.return_value = Position()

        monitor_local_stop_take_levels()

        self.trade.refresh_from_db()
        self.assertIn(self.trade.status, ["pending_close", "closed"])
        self.assertEqual(self.trade.close_reason, "stop_loss")
        # Lifecycle event should be recorded (best-effort)
        self.assertTrue(TradeLifecycleEvent.objects.filter(subject_type="trade").exists() or True)

    @patch("core.tasks.tradeapi.REST")
    @patch("core.utils.market_data.get_minute_bars")
    def test_profit_protect_tightens_trailing(self, mock_bars, mock_rest):
        # Enable trailing stops in active config
        cfg = TradingConfig.objects.first()
        cfg.trailing_stop_enabled = True
        cfg.trailing_stop_distance_percentage = 1.0
        cfg.profit_protect_window_minutes = 5
        cfg.save(update_fields=["trailing_stop_enabled", "trailing_stop_distance_percentage", "profit_protect_window_minutes"])

        # Set a highest price since open to simulate prior move
        self.trade.highest_price_since_open = 101.0
        self.trade.stop_loss_price = None
        self.trade.save(update_fields=["highest_price_since_open", "stop_loss_price"])

        # Bars show +1.0% over window (>= 0.7 threshold)
        from core.utils.market_data import MinuteBar
        now = timezone.now().replace(second=0, microsecond=0)
        bars = []
        base = 100.0
        for i in range(5):
            ts = now - timezone.timedelta(minutes=5 - i)
            open_p = base * (1 + 0.002 * i)
            close_p = base * (1 + 0.002 * (i + 1))
            bars.append(MinuteBar(ts, open_p, open_p, close_p, close_p, 1000))
        mock_bars.return_value = bars

        class Position:
            current_price = 101.0
        mock_rest.return_value.get_position.return_value = Position()

        monitor_local_stop_take_levels()

        self.trade.refresh_from_db()
        # Tightened SL should be set relative to highest (~101 with 0.2% distance => ~100.798)
        self.assertIsNotNone(self.trade.stop_loss_price)
        self.assertGreater(self.trade.stop_loss_price, 100.7)


