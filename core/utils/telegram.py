"""Backwards-compatible re-exports for Telegram utilities moved to `telegram_bot` app."""
from telegram_bot.utils import (
    get_telegram_config,
    send_telegram_message,
    ALERT_MAP,
    is_alert_enabled,
    send_system_error_alert,
)

