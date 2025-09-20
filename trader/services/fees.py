"""Thin wrapper around existing Alpaca fees utilities to keep API stable."""

from core.utils.alpaca_fees import (
    get_alpaca_api_client as _core_get_alpaca_api_client,
    fetch_trade_fees as _core_fetch_trade_fees,
    fetch_fees_for_trade_period as _core_fetch_fees_for_trade_period,
)


def get_alpaca_api_client():
    return _core_get_alpaca_api_client()


def fetch_trade_fees(symbol, trade_time, quantity, side):
    return _core_fetch_trade_fees(symbol, trade_time, quantity, side)


def fetch_fees_for_trade_period(symbol, start_time, end_time):
    return _core_fetch_fees_for_trade_period(symbol, start_time, end_time)


