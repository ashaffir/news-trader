import types
from datetime import datetime, timedelta

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
        "opened_at": datetime.utcnow() - timedelta(minutes=15),
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
    t = _trade(status="closed", realized_pnl=12.34, closed_at=datetime.utcnow())
    text = format_trade_detail(t)
    assert "P&L" in text and "$12.34" in text


def test_format_config():
    cfg = types.SimpleNamespace(
        bot_enabled=True,
        autostart=False,
        max_daily_trades=10,
        max_concurrent_open_trades=5,
        default_position_size=100.0,
        market_hours_only=True,
        trailing_stop_enabled=False,
    )
    alerts = types.SimpleNamespace(enabled=True)
    text = format_config(cfg, alerts, stats={"closed_count": 2, "win_rate": "50%", "avg_hold": "10m", "avg_pnl": "$1.00"})
    assert "Configuration" in text and "Stats" in text


