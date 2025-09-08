from django.test import TestCase

from core.models import TrackedCompany, Trade
from core.views import sync_alpaca_positions_to_database


class TradeSyncTests(TestCase):
    def setUp(self):
        TrackedCompany.objects.get_or_create(symbol="MSFT", defaults={"name": "Microsoft"})

    def test_sync_positions_idempotent_single_trade(self):
        positions = [
            {
                "symbol": "MSFT",
                "qty": "10",
                "market_value": "1000",
                "avg_entry_price": "100",
                "unrealized_pl": "50",
            }
        ]

        # First sync should create the trade
        sync_alpaca_positions_to_database(positions)
        # Second sync should NOT create a duplicate
        sync_alpaca_positions_to_database(positions)

        trades = Trade.objects.filter(
            alpaca_order_id="position_MSFT", status__in=["open", "pending", "pending_close"]
        )
        self.assertEqual(trades.count(), 1)

    def test_sync_positions_updates_existing_trade(self):
        # Initial position
        positions_initial = [
            {
                "symbol": "MSFT",
                "qty": "10",
                "market_value": "1000",
                "avg_entry_price": "100",
                "unrealized_pl": "50",
            }
        ]
        sync_alpaca_positions_to_database(positions_initial)

        trade = Trade.objects.get(alpaca_order_id="position_MSFT")
        self.assertEqual(int(trade.quantity), 10)
        self.assertAlmostEqual(float(trade.unrealized_pnl), 50.0)

        # Updated position (reduced quantity and changed P&L)
        positions_updated = [
            {
                "symbol": "MSFT",
                "qty": "8",
                "market_value": "800",
                "avg_entry_price": "100",
                "unrealized_pl": "70",
            }
        ]
        sync_alpaca_positions_to_database(positions_updated)

        trade.refresh_from_db()
        self.assertEqual(int(trade.quantity), 8)
        self.assertAlmostEqual(float(trade.unrealized_pnl), 70.0)

    def test_sync_closed_record_does_not_reopen_if_active_exists(self):
        # Create a closed trade for MSFT
        tc = TrackedCompany.objects.get(symbol="MSFT")
        closed = Trade.objects.create(
            symbol="MSFT",
            tracked_company=tc,
            status="closed",
            quantity=5,
            entry_price=90.0,
            closed_at=None,
        )
        # Create an active open trade for MSFT
        active = Trade.objects.create(
            symbol="MSFT",
            tracked_company=tc,
            status="open",
            quantity=9,
            entry_price=95.0,
            alpaca_order_id=None,
        )

        # Incoming live position
        positions = [
            {
                "symbol": "MSFT",
                "qty": "9",
                "market_value": "900",
                "avg_entry_price": "100",
                "unrealized_pl": "60",
            }
        ]

        sync_alpaca_positions_to_database(positions)

        # Closed one should remain closed
        closed.refresh_from_db()
        self.assertEqual(closed.status, "closed")

        # Active one should be updated and have stable alpaca id set
        active.refresh_from_db()
        self.assertEqual(int(active.quantity), 9)
        self.assertEqual(active.alpaca_order_id, "position_MSFT")


