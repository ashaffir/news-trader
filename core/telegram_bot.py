"""Backwards-compatible shim re-exporting the Telegram bot service from `telegram_bot` app."""

from telegram_bot.bot import (
    TelegramBotService,
    start_telegram_bot,
    stop_telegram_bot,
    get_bot_service,
)


