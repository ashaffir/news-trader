"""
Telegram Bot for News Trader - Interactive commands for bot control.

This module provides two-way Telegram integration allowing users to:
- Enable/disable the trading bot
- Get P&L reports (individual trades and totals) 
- Enable/disable alert notifications
- Get bot status and trading summaries
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import django
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Q
from asgiref.sync import sync_to_async

# Telegram bot imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    MessageHandler,
    filters
)
try:
    # Use explicit HTTPX request configuration to improve resilience
    from telegram.request import HTTPXRequest
    try:
        # HTTPVersion is available in newer PTB; fall back gracefully if missing
        from telegram.request import HTTPVersion  # type: ignore
    except Exception:  # pragma: no cover - optional import
        HTTPVersion = None  # type: ignore
except Exception:  # pragma: no cover - if request backend changes, continue with defaults
    HTTPXRequest = None  # type: ignore
    HTTPVersion = None  # type: ignore

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Main Telegram bot service for handling commands."""
    
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.authorized_chat_ids = self._get_authorized_chat_ids()
        self.application = None
    
    async def _check_database_connection(self, update: Update) -> bool:
        """Check database connection and send error message if failed."""
        try:
            # Important: fetch the DB connection INSIDE the worker thread,
            # otherwise the thread-affine DatabaseWrapper leaks across threads
            # and Django raises a thread ownership error.
            def _ensure():
                from django.db import connections, DEFAULT_DB_ALIAS
                conn = connections[DEFAULT_DB_ALIAS]
                conn.ensure_connection()

            await sync_to_async(_ensure, thread_sensitive=True)()
            return True
        except Exception as e:
            if "could not translate host name" in str(e) or "db" in str(e):
                await update.message.reply_text(
                    "⚠️ **Database not available**\n\n"
                    "You're running outside Docker. For full functionality:\n"
                    "• `docker-compose up -d`\n"
                    "• Or use SQLite: set `DATABASE_URL=` in .env", 
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ Database error: {str(e)}")
            return False
        
    def _get_authorized_chat_ids(self) -> set:
        """Get authorized chat IDs from environment."""
        chat_ids_str = os.getenv("TELEGRAM_AUTHORIZED_CHATS", "")
        if not chat_ids_str:
            # Fallback to legacy TELEGRAM_CHAT_ID
            legacy_chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if legacy_chat_id:
                chat_ids_str = legacy_chat_id
        
        try:
            return {int(chat_id.strip()) for chat_id in chat_ids_str.split(",") if chat_id.strip()}
        except ValueError:
            logger.warning("Invalid chat IDs in TELEGRAM_AUTHORIZED_CHATS")
            return set()
    
    def is_authorized(self, chat_id: int) -> bool:
        """Check if chat ID is authorized to use the bot."""
        return chat_id in self.authorized_chat_ids
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access. Contact administrator.")
            return
            
        welcome_text = """
🤖 **News Trader Bot Control**

Available commands:
• `/status` - Get bot status and trading overview
• `/enable` - Enable trading bot
• `/disable` - Disable trading bot
• `/pnl` - Get P&L summary (today and total)
• `/trades` - Get recent trades report
• `/alerts_on` - Enable notifications
• `/alerts_off` - Disable notifications
• `/help` - Show this help message

Use the commands to control your trading bot remotely!
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not self.is_authorized(update.effective_chat.id):
            return
        await self.start_command(update, context)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show bot status and trading overview."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            # Check database connection first
            if not await self._check_database_connection(update):
                return
                
            # Get trading config and alert settings
            from core.models import TradingConfig, AlertSettings, Trade
            
            config = await sync_to_async(TradingConfig.objects.filter(is_active=True).first)()
            alerts = await sync_to_async(AlertSettings.objects.order_by("-created_at").first)()
            
            # Get trading stats
            today = timezone.now().date()
            today_trades = await sync_to_async(
                lambda: list(Trade.objects.filter(created_at__date=today))
            )()
            
            open_trades = await sync_to_async(
                lambda: list(Trade.objects.filter(status__in=['open', 'pending', 'pending_close']))
            )()
            
            # Calculate P&L
            total_realized_pnl = await sync_to_async(
                lambda: Trade.objects.filter(realized_pnl__isnull=False).aggregate(
                    total=Sum('realized_pnl')
                )['total'] or 0.0
            )()
            
            total_unrealized_pnl = sum(trade.unrealized_pnl or 0.0 for trade in open_trades)
            
            # Bot status
            bot_status = "🟢 ENABLED" if (config and config.bot_enabled) else "🔴 DISABLED"
            alerts_status = "🔔 ON" if (alerts and alerts.enabled) else "🔕 OFF"
            
            status_text = (
                "📊 Trading Bot Status\n\n"
                f"🤖 Bot: {bot_status}\n"
                f"🔔 Alerts: {alerts_status}\n\n"
                "📈 Trading Summary\n"
                f"• Open positions: {len(open_trades)}\n"
                f"• Today's trades: {len(today_trades)}\n"
                f"• Total realized P&L: ${total_realized_pnl:,.2f}\n"
                f"• Unrealized P&L: ${total_unrealized_pnl:,.2f}\n\n"
                "⚙️ Configuration\n"
                f"• Max daily trades: {config.max_daily_trades if config else 'N/A'}\n"
                f"• Max concurrent: {config.max_concurrent_open_trades if config else 'N/A'}\n"
                f"• Position size: ${config.default_position_size if config else 'N/A'}"
            )
            
            # Add quick action buttons
            keyboard = [
                [
                    InlineKeyboardButton("🟢 Enable Bot" if not (config and config.bot_enabled) else "🔴 Disable Bot", 
                                       callback_data="toggle_bot"),
                    InlineKeyboardButton("🔔 Alerts On" if not (alerts and alerts.enabled) else "🔕 Alerts Off", 
                                       callback_data="toggle_alerts")
                ],
                [
                    InlineKeyboardButton("📊 P&L Report", callback_data="pnl_report"),
                    InlineKeyboardButton("📋 Recent Trades", callback_data="recent_trades")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(status_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await update.message.reply_text(f"❌ Error getting status: {str(e)}")
    
    async def enable_bot_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /enable command - enable the trading bot."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            # Check database connection first
            if not await self._check_database_connection(update):
                return
                
            from core.models import TradingConfig
            from core.utils.telegram import send_telegram_message
            
            config = await sync_to_async(TradingConfig.objects.filter(is_active=True).first)()
            if not config:
                await update.message.reply_text("❌ No active trading configuration found.")
                return
            
            if config.bot_enabled:
                await update.message.reply_text("ℹ️ Bot is already enabled.")
                return
            
            # Enable the bot
            config.bot_enabled = True
            await sync_to_async(config.save)(update_fields=['bot_enabled'])
            
            # Send notification via existing telegram utils
            await sync_to_async(send_telegram_message)(
                "🟢 Trading bot has been ENABLED via Telegram command"
            )
            
            await update.message.reply_text("✅ Trading bot has been **ENABLED**!", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error enabling bot: {e}")
            await update.message.reply_text(f"❌ Error enabling bot: {str(e)}")
    
    async def disable_bot_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /disable command - disable the trading bot."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            from core.models import TradingConfig
            from core.utils.telegram import send_telegram_message
            
            config = await sync_to_async(TradingConfig.objects.filter(is_active=True).first)()
            if not config:
                await update.message.reply_text("❌ No active trading configuration found.")
                return
            
            if not config.bot_enabled:
                await update.message.reply_text("ℹ️ Bot is already disabled.")
                return
            
            # Disable the bot
            config.bot_enabled = False
            await sync_to_async(config.save)(update_fields=['bot_enabled'])
            
            # Send notification
            await sync_to_async(send_telegram_message)(
                "🔴 Trading bot has been DISABLED via Telegram command"
            )
            
            await update.message.reply_text("🔴 Trading bot has been **DISABLED**!", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error disabling bot: {e}")
            await update.message.reply_text(f"❌ Error disabling bot: {str(e)}")
    
    async def pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pnl command - show P&L summary."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            from core.models import Trade
            
            # Get time ranges
            today = timezone.now().date()
            week_ago = today - timedelta(days=7)
            month_ago = today - timedelta(days=30)
            
            # Total P&L (all time)
            total_realized = await sync_to_async(
                lambda: Trade.objects.filter(realized_pnl__isnull=False).aggregate(
                    total=Sum('realized_pnl')
                )['total'] or 0.0
            )()
            
            # Today's P&L
            today_realized = await sync_to_async(
                lambda: Trade.objects.filter(
                    closed_at__date=today, 
                    realized_pnl__isnull=False
                ).aggregate(total=Sum('realized_pnl'))['total'] or 0.0
            )()
            
            # This week's P&L
            week_realized = await sync_to_async(
                lambda: Trade.objects.filter(
                    closed_at__date__gte=week_ago,
                    realized_pnl__isnull=False
                ).aggregate(total=Sum('realized_pnl'))['total'] or 0.0
            )()
            
            # This month's P&L  
            month_realized = await sync_to_async(
                lambda: Trade.objects.filter(
                    closed_at__date__gte=month_ago,
                    realized_pnl__isnull=False
                ).aggregate(total=Sum('realized_pnl'))['total'] or 0.0
            )()
            
            # Current unrealized P&L from open positions
            open_trades = await sync_to_async(
                lambda: list(Trade.objects.filter(status__in=['open', 'pending', 'pending_close']))
            )()
            
            total_unrealized = sum(trade.unrealized_pnl or 0.0 for trade in open_trades)
            
            # Format P&L with emojis
            def format_pnl(amount):
                if amount > 0:
                    return f"🟢 +${amount:,.2f}"
                elif amount < 0:
                    return f"🔴 ${amount:,.2f}"
                else:
                    return f"⚪ ${amount:,.2f}"
            
            pnl_text = (
                "💰 P&L Summary\n\n"
                f"📅 Today: {format_pnl(today_realized)}\n"
                f"📆 This Week: {format_pnl(week_realized)}\n"
                f"🗓️ This Month: {format_pnl(month_realized)}\n"
                f"🏆 Total (All Time): {format_pnl(total_realized)}\n\n"
                f"🔄 Current Unrealized: {format_pnl(total_unrealized)}\n"
                f"💵 Net Position: {format_pnl(total_realized + total_unrealized)}\n\n"
                f"📊 Open Positions: {len(open_trades)}"
            )
            
            # Reply to either a direct message or a callback message
            message_obj = update.message or (update.callback_query.message if update.callback_query else None)
            if message_obj:
                await message_obj.reply_text(pnl_text)
            else:
                # Fallback: send via bot directly
                await context.bot.send_message(chat_id=update.effective_chat.id, text=pnl_text)
            
        except Exception as e:
            logger.error(f"Error in P&L command: {e}")
            message_obj = update.message or (update.callback_query.message if update.callback_query else None)
            if message_obj:
                await message_obj.reply_text(f"❌ Error getting P&L: {str(e)}")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Error getting P&L: {str(e)}")
    
    async def trades_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trades command - show recent trades."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            from core.models import Trade
            
            # Get recent trades (last 10)
            recent_trades = await sync_to_async(
                lambda: list(Trade.objects.order_by('-created_at')[:10])
            )()
            
            if not recent_trades:
                message_obj = update.message or (update.callback_query.message if update.callback_query else None)
                if message_obj:
                    await message_obj.reply_text("📭 No trades found.")
                else:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text="📭 No trades found.")
                return
            
            trades_text = "📋 Recent Trades (Last 10)\n\n"
            
            for trade in recent_trades:
                # Format trade info
                status_emoji = {
                    'open': '🟡',
                    'closed': '🟢' if (trade.realized_pnl or 0) >= 0 else '🔴',
                    'pending': '🟠',
                    'pending_close': '🟠',
                    'cancelled': '⚫',
                    'failed': '🔴'
                }.get(trade.status, '⚪')
                
                direction_emoji = '📈' if trade.direction == 'buy' else '📉'
                
                # P&L info
                if trade.status == 'closed' and trade.realized_pnl is not None:
                    pnl_text = f"${trade.realized_pnl:,.2f}"
                elif trade.status in ['open', 'pending_close'] and trade.unrealized_pnl:
                    pnl_text = f"${trade.unrealized_pnl:,.2f} (unrealized)"
                else:
                    pnl_text = "N/A"
                
                # Timestamp
                time_str = trade.created_at.strftime("%m/%d %H:%M")
                
                trades_text += f"{status_emoji} {direction_emoji} {trade.symbol} - {trade.quantity} @ ${trade.entry_price:.2f}\n"
                trades_text += f"   P&L: {pnl_text} | {time_str} | {trade.status.title()}\n\n"
            
            message_obj = update.message or (update.callback_query.message if update.callback_query else None)
            if message_obj:
                await message_obj.reply_text(trades_text)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=trades_text)
            
        except Exception as e:
            logger.error(f"Error in trades command: {e}")
            message_obj = update.message or (update.callback_query.message if update.callback_query else None)
            if message_obj:
                await message_obj.reply_text(f"❌ Error getting trades: {str(e)}")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Error getting trades: {str(e)}")
    
    async def alerts_on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts_on command - enable alerts."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            from core.models import AlertSettings
            
            settings, created = await sync_to_async(AlertSettings.objects.get_or_create)(
                defaults={'enabled': True}
            )
            
            if not created and settings.enabled:
                await update.message.reply_text("ℹ️ Alerts are already enabled.")
                return
            
            settings.enabled = True
            await sync_to_async(settings.save)()
            
            await update.message.reply_text("🔔 **Alerts have been ENABLED**!", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error enabling alerts: {e}")
            await update.message.reply_text(f"❌ Error enabling alerts: {str(e)}")
    
    async def alerts_off_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts_off command - disable alerts."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access.")
            return
        
        try:
            from core.models import AlertSettings
            
            settings = await sync_to_async(AlertSettings.objects.order_by('-created_at').first)()
            if not settings:
                await update.message.reply_text("ℹ️ No alert settings found - alerts are already disabled.")
                return
            
            if not settings.enabled:
                await update.message.reply_text("ℹ️ Alerts are already disabled.")
                return
            
            settings.enabled = False
            await sync_to_async(settings.save)()
            
            await update.message.reply_text("🔕 **Alerts have been DISABLED**!", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error disabling alerts: {e}")
            await update.message.reply_text(f"❌ Error disabling alerts: {str(e)}")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses."""
        if not self.is_authorized(update.effective_chat.id):
            await update.callback_query.answer("❌ Unauthorized access.")
            return
        
        query = update.callback_query
        await query.answer()
        
        if query.data == "toggle_bot":
            # Toggle bot enable/disable
            try:
                from core.models import TradingConfig
                config = await sync_to_async(TradingConfig.objects.filter(is_active=True).first)()
                if config:
                    config.bot_enabled = not config.bot_enabled
                    await sync_to_async(config.save)(update_fields=['bot_enabled'])
                    status = "ENABLED" if config.bot_enabled else "DISABLED"
                    await query.edit_message_text(f"✅ Trading bot has been **{status}**!", parse_mode='Markdown')
                else:
                    await query.edit_message_text("❌ No active trading configuration found.")
            except Exception as e:
                await query.edit_message_text(f"❌ Error: {str(e)}")
                
        elif query.data == "toggle_alerts":
            # Toggle alerts enable/disable
            try:
                from core.models import AlertSettings
                settings, created = await sync_to_async(AlertSettings.objects.get_or_create)(
                    defaults={'enabled': True}
                )
                if not created:
                    settings.enabled = not settings.enabled
                    await sync_to_async(settings.save)()
                status = "ENABLED" if settings.enabled else "DISABLED"
                await query.edit_message_text(f"🔔 Alerts have been **{status}**!", parse_mode='Markdown')
            except Exception as e:
                await query.edit_message_text(f"❌ Error: {str(e)}")
                
        elif query.data == "pnl_report":
            # Show P&L report
            await self.pnl_command(update, context)
            
        elif query.data == "recent_trades":
            # Show recent trades
            await self.trades_command(update, context)
    
    async def handle_unauthorized_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages from unauthorized users."""
        await update.message.reply_text("❌ Unauthorized access. Contact administrator.")
    
    def setup_handlers(self):
        """Set up all command and message handlers."""
        if not self.application:
            return
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("enable", self.enable_bot_command))
        self.application.add_handler(CommandHandler("disable", self.disable_bot_command))
        self.application.add_handler(CommandHandler("pnl", self.pnl_command))
        self.application.add_handler(CommandHandler("trades", self.trades_command))
        self.application.add_handler(CommandHandler("alerts_on", self.alerts_on_command))
        self.application.add_handler(CommandHandler("alerts_off", self.alerts_off_command))
        
        # Callback query handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # Handle unauthorized messages
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_unauthorized_message
        ))
    
    async def start_bot(self):
        """Start the Telegram bot."""
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment")
            return None
            
        if not self.authorized_chat_ids:
            logger.warning("No authorized chat IDs configured")
        
        # Build application with hardened HTTP settings to avoid httpx RemoteProtocolError
        builder = Application.builder().token(self.token)
        try:
            if HTTPXRequest:
                request_kwargs = {
                    "connect_timeout": 10.0,
                    "read_timeout": 70.0,
                    "write_timeout": 70.0,
                    "pool_timeout": 10.0,
                }
                # Prefer HTTP/1.1 to avoid intermittent HTTP/2 disconnects
                if HTTPVersion is not None:
                    request_kwargs["http_version"] = HTTPVersion.HTTP_1_1  # type: ignore
                else:
                    # Some PTB versions accept a string
                    request_kwargs["http_version"] = "1.1"
                builder = builder.request(HTTPXRequest(**request_kwargs))
            # Increase long-polling timeout for getUpdates
            if hasattr(builder, "get_updates_request_timeout"):
                builder = builder.get_updates_request_timeout(60)
        except Exception as e:
            logger.warning("Building HTTPXRequest failed, falling back to defaults: %s", e)
        
        self.application = builder.build()
        self.setup_handlers()
        
        logger.info("Starting Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        return self.application
    
    async def stop_bot(self):
        """Stop the Telegram bot."""
        if self.application:
            logger.info("Stopping Telegram bot...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()


# Global bot instance
_bot_service = None


async def start_telegram_bot():
    """Start the Telegram bot service."""
    global _bot_service
    if _bot_service is None:
        _bot_service = TelegramBotService()
    
    return await _bot_service.start_bot()


async def stop_telegram_bot():
    """Stop the Telegram bot service."""
    global _bot_service
    if _bot_service:
        await _bot_service.stop_bot()


def get_bot_service() -> Optional[TelegramBotService]:
    """Get the current bot service instance."""
    return _bot_service
