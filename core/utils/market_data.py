from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Tuple, Optional


@dataclass
class MinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def _to_utc(dt: datetime) -> datetime:
    try:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=dt_timezone.utc)
        return dt.astimezone(dt_timezone.utc)
    except Exception:
        return dt


def get_minute_bars(symbol: str, start: datetime, end: datetime) -> List[MinuteBar]:
    """Fetch minute bars from Alpaca. Prefer alpaca-py historical client, fallback to alpaca-trade-api.

    Returns an empty list on failure.
    """
    start = _to_utc(start)
    end = _to_utc(end)

    # Try alpaca-py
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        api_key = os.getenv("ALPACA_API_KEY") or ""
        api_secret = os.getenv("ALPACA_SECRET_KEY") or ""
        feed = (os.getenv("ALPACA_DATA_FEED") or "iex").upper()

        client = StockHistoricalDataClient(api_key, api_secret)
        req = StockBarsRequest(
            symbol_or_symbols=[symbol], timeframe=TimeFrame.Minute, start=start, end=end, feed=DataFeed[feed]
        )
        bars = client.get_stock_bars(req)
        df = getattr(bars, "df", None)
        rows: List[MinuteBar] = []
        if df is not None and not getattr(df, "empty", True):
            # Multi-index (symbol, timestamp)
            df = df.reset_index()
            for _, r in df.iterrows():
                try:
                    rows.append(
                        MinuteBar(
                            timestamp=r["timestamp"],
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                            volume=float(r["volume"]),
                        )
                    )
                except Exception:
                    continue
        if rows:
            return rows
    except Exception:
        pass

    # Fallback to alpaca-trade-api
    try:
        from alpaca_trade_api.rest import REST as OldREST, TimeFrame as OldTimeFrame

        def to_rfc3339(d: datetime) -> str:
            try:
                return d.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return d.strftime("%Y-%m-%dT%H:%M:%SZ")

        client = OldREST(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))
        feed = (os.getenv("ALPACA_DATA_FEED") or "iex").lower()
        try:
            df = client.get_bars(symbol, OldTimeFrame.Minute, to_rfc3339(start), to_rfc3339(end), adjustment='raw', feed=feed).df
        except Exception:
            df = client.get_bars(symbol, '1Min', to_rfc3339(start), to_rfc3339(end), feed=feed).df
        rows: List[MinuteBar] = []
        if df is not None and not getattr(df, "empty", True):
            for idx, r in df.iterrows():
                try:
                    ts = getattr(idx, "to_pydatetime", lambda: idx)()
                    rows.append(
                        MinuteBar(
                            timestamp=ts,
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                            volume=float(r["volume"]),
                        )
                    )
                except Exception:
                    continue
        return rows
    except Exception:
        return []


def _align_to_minute(dt: datetime) -> datetime:
    dt = _to_utc(dt)
    return dt.replace(second=0, microsecond=0)


def compute_entry_confirmations(
    symbol: str,
    detection_time: datetime,
    window_minutes: int,
    volume_ma_window: int,
    direction: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Compute price change over N minutes and volume spike ratio.

    - Price change: (close_N - open_1)/open_1 * 100, signed by direction.
    - Volume ratio: sum(volume first N bars) / mean(volume of previous M bars).
    Returns (price_change_pct_signed, volume_ratio). None if insufficient data.
    """
    if window_minutes <= 0 or volume_ma_window <= 0:
        return None, None, None, None

    t0 = _align_to_minute(detection_time)  # first complete minute
    t_start = t0
    t_end = t_start + timedelta(minutes=window_minutes)

    # Fetch bars for confirmation window and prior MA window
    prior_start = t_start - timedelta(minutes=volume_ma_window)
    prior_end = t_start

    window_bars = get_minute_bars(symbol, t_start, t_end)
    prior_bars = get_minute_bars(symbol, prior_start, prior_end)

    if not window_bars or len(window_bars) < window_minutes:
        return None, None, None, None
    if not prior_bars or len(prior_bars) < max(3, min(10, volume_ma_window // 2)):
        # Require some reasonable history; maintain 4-tuple contract
        return None, None, None, None

    # Sort by timestamp just in case
    window_bars = sorted(window_bars, key=lambda b: b.timestamp)
    prior_bars = sorted(prior_bars, key=lambda b: b.timestamp)

    open_first = float(window_bars[0].open)
    close_last = float(window_bars[min(len(window_bars), window_minutes) - 1].close)
    if open_first <= 0:
        return None, None, None, None

    raw_change_pct = (close_last - open_first) / open_first * 100.0
    signed_change = raw_change_pct
    if direction.lower() == "sell":
        signed_change = -raw_change_pct

    vol_n = sum(float(b.volume or 0.0) for b in window_bars[:window_minutes])
    prior = prior_bars[-volume_ma_window:]
    vol_ma = sum(float(b.volume or 0.0) for b in prior) / max(1, len(prior))
    if vol_ma <= 0:
        vol_ratio = None
    else:
        vol_ratio = vol_n / vol_ma

    return signed_change, vol_ratio, vol_n, vol_ma


def compute_signed_price_change_over_window(
    symbol: str,
    end_time: datetime,
    window_minutes: int,
    direction: str,
) -> Optional[float]:
    """Compute signed price change over the last N minutes ending at end_time.

    Uses open of first bar and close of last bar within the window, signed by direction.
    Returns None if insufficient data.
    """
    if window_minutes <= 0:
        return None
    end_time = _align_to_minute(end_time)
    start_time = end_time - timedelta(minutes=window_minutes)
    bars = get_minute_bars(symbol, start_time, end_time)
    if not bars or len(bars) < window_minutes:
        return None
    bars = sorted(bars, key=lambda b: b.timestamp)
    open_first = float(bars[0].open)
    close_last = float(bars[min(len(bars), window_minutes) - 1].close)
    if open_first <= 0:
        return None
    raw = (close_last - open_first) / open_first * 100.0
    return raw if direction.lower() == "buy" else -raw


