"""Text formatters for Telegram bot outputs.

Pure formatting helpers that accept model instances or plain dicts and
return human-readable strings. Kept free of Telegram SDK and side effects
to enable straightforward unit testing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional


def format_money(value: Optional[float]) -> str:
    """Format a numeric amount as dollar text with sign and 2 decimals."""
    try:
        if value is None:
            return "$0.00"
        sign = "+" if float(value) > 0 else ""
        return f"{sign}${float(value):,.2f}"
    except Exception:
        return "$0.00"


def format_pnl_emoji(value: float) -> str:
    """Return emoji + formatted money for P&L-like values."""
    try:
        amt = float(value)
    except Exception:
        amt = 0.0
    if amt > 0:
        return f"🟢 +${amt:,.2f}"
    if amt < 0:
        return f"🔴 ${amt:,.2f}"
    return f"⚪ ${amt:,.2f}"


def _duration_str(start: Optional[datetime], end: Optional[datetime] = None) -> str:
    if not start:
        return "-"
    end = end or datetime.utcnow()
    delta: timedelta = end - start
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours}h {rem}m"


def format_open_trades(trades: Iterable) -> str:
    """Format a list of open/pending_close trades into a concise report."""
    trades = list(trades)
    if not trades:
        return "📭 No open positions."

    lines = ["📂 Open Positions\n"]
    for t in trades:
        status_emoji = "🟡" if getattr(t, "status", "open") != "pending_close" else "🟠"
        direction_emoji = "📈" if getattr(t, "direction", "buy") == "buy" else "📉"
        qty = getattr(t, "quantity", 0)
        entry = getattr(t, "entry_price", 0.0) or 0.0
        unreal = getattr(t, "unrealized_pnl", 0.0) or 0.0
        sl = getattr(t, "stop_loss_price", None)
        tp = getattr(t, "take_profit_price", None)
        opened_at = getattr(t, "opened_at", None) or getattr(t, "created_at", None)
        age = _duration_str(opened_at)

        lines.append(
            f"{status_emoji} {direction_emoji} #{getattr(t,'id','?')} {getattr(t,'symbol','?')} "
            f"x{qty:g} @ ${float(entry):.2f} | UPL: {format_pnl_emoji(unreal)} | {age}"
        )
        if sl or tp:
            stp = []
            if sl:
                stp.append(f"SL ${float(sl):.2f}")
            if tp:
                stp.append(f"TP ${float(tp):.2f}")
            lines.append("   " + " · ".join(stp))
        lines.append("")

    return "\n".join(lines).rstrip()


def format_trade_detail(trade) -> str:
    """Detailed single-trade view suitable for `/trade` output."""
    if not trade:
        return "❌ Trade not found."

    status = getattr(trade, "status", "-")
    direction_emoji = "📈" if getattr(trade, "direction", "buy") == "buy" else "📉"
    pnl = getattr(trade, "realized_pnl", None) if status == "closed" else getattr(trade, "unrealized_pnl", 0.0)
    opened_at = getattr(trade, "opened_at", None) or getattr(trade, "created_at", None)
    duration = _duration_str(opened_at, getattr(trade, "closed_at", None))

    lines = [
        "🔎 Trade Detail\n",
        f"{direction_emoji} #{getattr(trade,'id','?')} {getattr(trade,'symbol','?')} ({status})",
        f"Qty: {getattr(trade,'quantity',0):g}",
        f"Entry: ${float(getattr(trade,'entry_price',0.0) or 0.0):.2f}",
    ]
    if getattr(trade, "exit_price", None) is not None:
        lines.append(f"Exit: ${float(trade.exit_price):.2f}")
    if getattr(trade, "stop_loss_price", None) is not None or getattr(trade, "take_profit_price", None) is not None:
        extras = []
        if getattr(trade, "stop_loss_price", None) is not None:
            extras.append(f"SL ${float(trade.stop_loss_price):.2f}")
        if getattr(trade, "take_profit_price", None) is not None:
            extras.append(f"TP ${float(trade.take_profit_price):.2f}")
        lines.append(" | ".join(extras))

    lines.extend([
        f"P&L: {format_pnl_emoji(float(pnl or 0.0))}",
        f"Duration: {duration}",
    ])
    if getattr(trade, "close_reason", None):
        lines.append(f"Close reason: {trade.close_reason}")
    return "\n".join(lines)


def format_config(config, alerts, stats: Optional[dict] = None) -> str:
    """Format trading config and optional aggregate stats."""
    if not config:
        return "❌ No active trading configuration found."

    lines = [
        "⚙️ Configuration\n",
        f"Bot: {'🟢 ENABLED' if getattr(config,'bot_enabled', False) else '🔴 DISABLED'}",
        f"Autostart: {'ON' if getattr(config,'autostart', False) else 'OFF'}",
        f"Max daily trades: {getattr(config,'max_daily_trades','-')}",
        f"Max concurrent: {getattr(config,'max_concurrent_open_trades','-')}",
        f"Position size: ${float(getattr(config,'default_position_size',0.0) or 0.0):.2f}",
        f"Market hours only: {'Yes' if getattr(config,'market_hours_only', True) else 'No'}",
        f"Trailing stop: {'ON' if getattr(config,'trailing_stop_enabled', False) else 'OFF'}",
        f"Alerts: {'🔔 ON' if (alerts and getattr(alerts,'enabled', False)) else '🔕 OFF'}",
    ]
    if stats:
        lines.extend([
            "",
            "📊 Stats",
            f"Closed trades: {stats.get('closed_count', 0)} | Win rate: {stats.get('win_rate','0%')}",
            f"Avg hold: {stats.get('avg_hold','-')} | Avg P&L: {stats.get('avg_pnl','$0.00')}",
        ])
    return "\n".join(lines)


def format_activity(logs: Iterable) -> str:
    logs = list(logs)
    if not logs:
        return "📭 No recent activity."
    lines = ["📝 Recent Activity\n"]
    for a in logs:
        ts = getattr(a, "created_at", None)
        tstr = ts.strftime("%m/%d %H:%M") if ts else "-"
        lines.append(f"{tstr} • {getattr(a,'activity_type','-')}: {getattr(a,'message','').strip()[:140]}")
    return "\n".join(lines)


