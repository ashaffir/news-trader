import os
import logging

logger = logging.getLogger(__name__)


def get_alpaca_client():
    """Return an Alpaca REST client if credentials are configured; else None."""
    try:
        import alpaca_trade_api as tradeapi
    except Exception as e:
        logger.debug(f"alpaca-trade-api import failed: {e}")
        return None

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not api_key or not secret_key:
        return None
    try:
        return tradeapi.REST(api_key, secret_key, base_url=base_url)
    except Exception as e:
        logger.warning(f"Failed to init Alpaca client: {e}")
        return None


