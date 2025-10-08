import types
from datetime import datetime, timedelta, timezone as dt_timezone

from telegram_bot.formatters import (
    format_money,
    format_pnl_emoji,
    format_open_trades,
    format_trade_detail,
    format_config,
)


def _trade(**kwargs):
    d = {
        "id": 1,
        "symbol": "AAPL",
        "direction": "buy",
        "quantity": 2,
        "entry_price": 100.0,
        "unrealized_pnl": 5.0,
        "status": "open",
        "opened_at": datetime.now(dt_timezone.utc) - timedelta(minutes=15),
    }
    d.update(kwargs)
    return types.SimpleNamespace(**d)


def test_format_pnl_emoji():
    assert "🟢" in format_pnl_emoji(10)
    assert "🔴" in format_pnl_emoji(-1)
    assert "⚪" in format_pnl_emoji(0)


def test_format_open_trades_empty():
    assert "No open" in format_open_trades([])


def test_format_open_trades_basic():
    text = format_open_trades([_trade()])
    assert "AAPL" in text and "UPL" in text


def test_format_trade_detail_closed():
    t = _trade(status="closed", realized_pnl=12.34, closed_at=datetime.now(dt_timezone.utc))
    text = format_trade_detail(t)
    assert "P&L" in text and "$12.34" in text


def test_format_config():
    cfg = types.SimpleNamespace(
        bot_enabled=True,
        max_daily_trades=10,
        max_concurrent_open_trades=5,
        default_position_size=100.0,
        trailing_stop_enabled=False,
    )
    alerts = types.SimpleNamespace(enabled=True)
    text = format_config(cfg, alerts, stats={"closed_count": 2, "win_rate": "50%", "avg_hold": "10m", "avg_pnl": "$1.00"})
    assert "Configuration" in text and "Stats" in text


def test_duration_mixed_naive_aware():
    # Naive opened_at with aware now
    naive_open = datetime(2025, 1, 1, 12, 0, 0)  # naive, assumed UTC
    t = _trade(opened_at=naive_open)
    text = format_open_trades([t])
    assert "Open Positions" in text

    # Aware opened_at with naive closed_at in detail view
    aware_open = datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
    naive_close = datetime(2025, 1, 1, 13, 0, 0)  # naive
    t2 = _trade(status="closed", opened_at=aware_open, closed_at=naive_close, realized_pnl=0.0)
    detail = format_trade_detail(t2)
    assert "Duration" in detail


