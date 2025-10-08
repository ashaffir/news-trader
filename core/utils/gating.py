from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from django.utils import timezone
from django.db.models import Q

from core.models import TradingConfig, Post


def _is_weekend(now) -> bool:
    try:
        wd = int(now.weekday())  # Mon=0..Sun=6
        return wd >= 5
    except Exception:
        return False


def _is_market_open_now(now_utc: Optional[timezone.datetime] = None) -> bool:
    """Heuristic market-hours check in UTC (Mon-Fri 13:30-20:00). Ignores holidays."""
    try:
        if now_utc is None:
            now_utc = timezone.now()
        weekday = now_utc.weekday()  # Mon=0..Sun=6
        if weekday >= 5:
            return False
        minutes = now_utc.hour * 60 + now_utc.minute
        open_min = 13 * 60 + 30
        close_min = 20 * 60
        return open_min <= minutes < close_min
    except Exception:
        return False


def _is_market_open_broker_aware(now_utc: Optional[timezone.datetime] = None) -> bool:
    """Try broker clock first (Alpaca), fallback to heuristic window."""
    try:
        import os
        import alpaca_trade_api as tradeapi

        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        if key and secret:
            api = tradeapi.REST(key, secret, base_url, api_version="v2")
            clock = api.get_clock()
            return bool(getattr(clock, "is_open", False))
    except Exception:
        pass
    return _is_market_open_now(now_utc)


@dataclass
class GateState:
    # Inputs reflected
    bot_enabled: bool
    overnight_enabled: bool
    market_open: bool
    is_weekend: bool

    # Decisions
    allow_scrape: bool
    allow_analysis: bool
    allow_overnight_collection: bool
    allow_overnight_processing: bool
    allow_trading: bool

    # Operational hints
    backlog_count: int = 0
    mode: str = "off"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_gate(manual_test: bool = False, include_backlog: bool = True) -> Dict[str, Any]:
    """Compute the single source of truth for scraping/trading gates.

    Rules (as provided by product requirements):
    - Bot master switch controls EVERYTHING. If disabled, nothing runs (except manual tests).
    - Autostart merely toggles the bot at market open/close. Gate computation is independent of it.
    - No separate trading_enabled/market_hours_only flags. Trading is implicitly allowed only during market hours.
    - Weekends: overnight collection/processing may run; NO trading.
    - Market open with overnight backlog: process ALL overnight posts before regular scraping.
      Failures must be marked and not block the rest of the backlog.
    - manual_test=True bypasses bot_enabled for scraping/analysis, but NEVER enables trading.
    """

    cfg = TradingConfig.objects.filter(is_active=True).first()
    now = timezone.now()
    market_open = _is_market_open_broker_aware(now)
    weekend = _is_weekend(now)

    bot_enabled = bool(getattr(cfg, "bot_enabled", False))
    overnight_enabled = bool(getattr(cfg, "overnight_enabled", False))

    # Default OFF
    gate = GateState(
        bot_enabled=bot_enabled,
        autostart=False,
        overnight_enabled=overnight_enabled,
        market_open=market_open,
        is_weekend=weekend,
        allow_scrape=False,
        allow_analysis=False,
        allow_overnight_collection=False,
        allow_overnight_processing=False,
        allow_trading=False,
        backlog_count=0,
        mode="off",
        reason="bot_disabled" if not bot_enabled else "",
    )

    if manual_test:
        # Allow local/manual runs for diagnostics without opening trades
        gate.allow_scrape = True
        gate.allow_analysis = True
        gate.allow_overnight_collection = overnight_enabled and not market_open
        gate.allow_overnight_processing = False
        gate.allow_trading = False
        gate.mode = "manual_test"
        gate.reason = "manual_test_mode"
        return gate.to_dict()

    if not bot_enabled:
        return gate.to_dict()

    # When the bot is enabled
    if weekend:
        # No trading on weekends; allow overnight collection/processing when enabled
        gate.allow_trading = False
        gate.allow_scrape = overnight_enabled  # allow scrapers to collect overnight posts only
        gate.allow_analysis = overnight_enabled
        gate.allow_overnight_collection = overnight_enabled
        gate.allow_overnight_processing = overnight_enabled
        gate.mode = "weekend_overnight" if overnight_enabled else "weekend_idle"
        gate.reason = "weekend"
        return gate.to_dict()

    # Weekday
    if market_open:
        # Process overnight backlog first when market is open
        backlog_count = 0
        if include_backlog and overnight_enabled:
            try:
                backlog_count = (
                    Post.objects.filter(
                        overnight=True,
                        is_stale=False,
                        analysis__isnull=False,
                    )
                    .filter(
                        Q(analysis__enter_status__in=[
                            "created",
                            "eligible",
                            "waiting_confirmation",
                        ])
                        | Q(analysis__enter_status__isnull=True)
                    )
                    .count()
                )
            except Exception:
                backlog_count = 0

        gate.backlog_count = backlog_count
        gate.allow_overnight_processing = overnight_enabled and backlog_count > 0
        gate.allow_scrape = backlog_count == 0
        gate.allow_analysis = True
        gate.allow_trading = True  # trading only during market hours by definition
        gate.mode = "open_process_overnight" if gate.allow_overnight_processing else "open_periodic"
        gate.reason = "overnight_backlog" if gate.allow_overnight_processing else "normal_market_hours"
        return gate.to_dict()

    # Market closed on weekday
    if overnight_enabled:
        gate.allow_scrape = True
        gate.allow_analysis = True
        gate.allow_overnight_collection = True
        gate.mode = "closed_overnight_collect"
        gate.reason = "market_closed_collect_overnight"
    else:
        gate.mode = "closed_idle"
        gate.reason = "market_closed"
    gate.allow_trading = False
    gate.allow_overnight_processing = False
    return gate.to_dict()


