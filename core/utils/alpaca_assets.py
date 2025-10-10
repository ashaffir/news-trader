from __future__ import annotations

from typing import Tuple


def is_valid_tradable_symbol(api, symbol: str) -> Tuple[bool, str]:
    """Validate that a symbol exists in Alpaca and is tradable.

    Returns (True, "OK") when valid; otherwise (False, reason).
    """
    if not symbol or not isinstance(symbol, str):
        return False, "Empty or invalid symbol"

    sym = symbol.strip().upper()
    if not sym:
        return False, "Empty symbol after normalization"

    try:
        asset = api.get_asset(sym)
    except Exception as e:
        return False, f"Asset lookup failed: {e}"

    if not asset:
        return False, "Asset not found"

    try:
        tradable = bool(getattr(asset, "tradable", False))
        status = (getattr(asset, "status", "") or "").lower()
        # Some SDKs may expose .easy_to_borrow or .shortable; not required for validation here.
    except Exception:
        tradable = False
        status = ""

    if not tradable:
        return False, "Asset not tradable"
    if status and status != "active":
        return False, f"Asset status is '{status}'"

    return True, "OK"


