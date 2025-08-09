import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_telegram_config() -> tuple[Optional[str], Optional[str]]:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
    return token, chat_id


def send_telegram_message(message: str) -> bool:
    token, chat_id = get_telegram_config()
    logger.info(
        "Telegram send requested. token_present=%s chat_id_present=%s message_len=%s",
        bool(token), bool(chat_id), len(message or ""),
    )
    if not token or not chat_id:
        logger.warning("Telegram config missing. token_present=%s chat_id_present=%s", bool(token), bool(chat_id))
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        ok = resp.status_code == 200
        logger.info("Telegram response status=%s ok=%s body_prefix=%s", resp.status_code, ok, (resp.text or "")[:120])
        return ok
    except Exception:
        logger.exception("Telegram send failed with exception")
        return False


ALERT_MAP = {
    "bot_status": "bot_status_enabled",
    "new_trade": "order_open_enabled",
    "trade_status_updated": "order_open_enabled",
    "trade_closed": "order_close_enabled",
    "trade_closed_conflict": "order_close_enabled",
    "trade_rejected": "trading_limit_enabled",
    "heartbeat": "heartbeat_enabled",
}


def is_alert_enabled(message_type: str) -> bool:
    from core.models import AlertSettings

    settings = AlertSettings.objects.order_by("-created_at").first()
    if not settings:
        logger.info("No AlertSettings found; alerts disabled for type=%s", message_type)
        return False
    if not settings.enabled:
        logger.info("AlertSettings disabled globally; type=%s", message_type)
        return False
    field = ALERT_MAP.get(message_type)
    if not field:
        logger.info("No toggle mapping for message_type=%s", message_type)
        return False
    enabled = getattr(settings, field, False)
    logger.info("Alert toggle check: type=%s field=%s enabled=%s", message_type, field, enabled)
    return enabled


