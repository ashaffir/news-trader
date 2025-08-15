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
import time
import threading
import socket
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import django
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Q
from asgiref.sync import sync_to_async
import redis

# Telegram bot imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict, NetworkError, TimedOut, RetryAfter
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    MessageHandler,
    filters
)
import httpx
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
        self._lock = None
        self._lock_thread = None
        self._lock_stop = threading.Event()

    # --- Distributed single-instance lock (Redis) ---
    def _redis_client(self):
        url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
        if not url or not url.startswith("redis"):
            return None
        try:
            return redis.Redis.from_url(url)
        except Exception:
            return None

    def _acquire_singleton_lock(self) -> bool:
        if not self.token:
            return False
        client = self._redis_client()
        if client is None:
            # No Redis available; assume single-instance per container
            return True
        key = f"telegram_bot_lock:{self.token}"
        value = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
        try:
            ok = client.set(key, value, nx=True, ex=120)
            if ok:
                self._lock = (client, key, value)
                # Start background refresher
                self._lock_stop.clear()
                self._lock_thread = threading.Thread(target=self._refresh_lock_loop, daemon=True)
                self._lock_thread.start()
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to acquire Redis lock for Telegram bot: {e}")
            return True  # Fail-open to not block in dev

    def _refresh_lock_loop(self):
        if not self._lock:
            return
        client, key, value = self._lock
        while not self._lock_stop.is_set():
            try:
                # Refresh only if we still own it
                current = client.get(key)
                if current and current.decode() == value:
                    client.expire(key, 120)
                else:
                    # Lost lock; request stop
                    logger.warning("Telegram bot lost singleton lock; stopping bot polling")
                    try:
                        # Trigger stop; application will be stopped in stop_bot
                        self._lock_stop.set()
                    except Exception:
                        pass
                    break
            except Exception:
                pass
            time.sleep(30)

    def _release_singleton_lock(self):
        try:
            self._lock_stop.set()
            if self._lock_thread:
                self._lock_thread.join(timeout=5)
        except Exception:
            pass
        if not self._lock:
            return
        client, key, value = self._lock
        try:
            # Delete only if owned
            current = client.get(key)
            if current and current.decode() == value:
                client.delete(key)
        except Exception:
            pass
        finally:
            self._lock = None
    
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
        
        # Enhanced error handler for network connectivity issues with automatic recovery
        async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
            err = getattr(context, 'error', None)
            
            if isinstance(err, Conflict):
                logger.error("Conflict detected during polling; stopping bot instance to avoid duplicate pollers.")
                try:
                    await self.stop_bot()
                except Exception:
                    pass
                    
            elif isinstance(err, (NetworkError, httpx.RemoteProtocolError, httpx.ConnectError)):
                logger.warning(f"Network error in Telegram bot: {type(err).__name__}: {err}")
                
                # For RemoteProtocolError specifically, attempt to restart polling
                if isinstance(err, httpx.RemoteProtocolError):
                    logger.info("Attempting to recover from RemoteProtocolError by restarting polling...")
                    asyncio.create_task(self._recover_from_network_error())
                
            elif isinstance(err, TimedOut):
                logger.debug(f"Telegram request timed out: {err}")
                # Timeout is normal for long polling, don't log as warning
                
            elif isinstance(err, RetryAfter):
                retry_after = err.retry_after
                logger.warning(f"Rate limited by Telegram API, retry after {retry_after} seconds")
                # The bot will automatically wait and retry
                
            else:
                # Log other unexpected errors
                logger.error(f"Unexpected error in Telegram bot: {type(err).__name__}: {err}")
                if update:
                    logger.error(f"Error occurred while processing update: {update}")
                
        self.application.add_error_handler(on_error)
    
    async def start_bot(self):
        """Start the Telegram bot."""
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment")
            return None
            
        if not self.authorized_chat_ids:
            logger.warning("No authorized chat IDs configured")
        
        # Enforce single instance across containers/processes
        if not self._acquire_singleton_lock():
            logger.error("Another Telegram bot instance is already polling (singleton lock not acquired). Skipping start.")
            return None
        
        # Build application with hardened HTTP settings and retry logic
        builder = Application.builder().token(self.token)
        try:
            if HTTPXRequest:
                request_kwargs = {
                    "connect_timeout": 15.0,   # Connection timeout
                    "read_timeout": 60.0,      # Read timeout for long polling
                    "write_timeout": 30.0,     # Write timeout
                    "pool_timeout": 10.0,      # Pool timeout
                    # Limit connections to reduce resource usage and improve stability
                    "pool_limits": httpx.Limits(
                        max_keepalive_connections=2, 
                        max_connections=5,
                        keepalive_expiry=30.0  # Keep connections alive for 30 seconds
                    )
                }
                
                # Prefer HTTP/1.1 to avoid intermittent HTTP/2 disconnects
                if HTTPVersion is not None:
                    request_kwargs["http_version"] = HTTPVersion.HTTP_1_1  # type: ignore
                else:
                    # Some PTB versions accept a string
                    request_kwargs["http_version"] = "1.1"
                    
                logger.info("Configuring Telegram bot with enhanced HTTP settings for resilience")
                builder = builder.request(HTTPXRequest(**request_kwargs))
            
            # Configure polling with conservative settings for better resilience
            builder = builder.get_updates_connect_timeout(15)
            builder = builder.get_updates_read_timeout(60)  
            builder = builder.get_updates_write_timeout(30)
            builder = builder.get_updates_pool_timeout(10)
            
            # Configure reasonable polling timeout
            if hasattr(builder, "get_updates_request_timeout"):
                builder = builder.get_updates_request_timeout(50)
                
        except Exception as e:
            logger.warning("Building HTTPXRequest with custom settings failed, falling back to defaults: %s", e)
        
        self.application = builder.build()
        self.setup_handlers()
        
        # Preflight: check if another poller is active to avoid conflict loops
        try:
            # Short timeout; we only need to detect Conflict
            await self.application.bot.get_updates(timeout=1)
        except Conflict:
            logger.error("Another Telegram poller is already running for this token (Conflict). Skipping start.")
            self._release_singleton_lock()
            return None
        except Exception:
            # Non-conflict errors will be handled by polling
            pass

        logger.info("Starting Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        
        # Start polling with automatic recovery
        await self._start_resilient_polling()
        
        # Start health monitoring in the background
        asyncio.create_task(self.monitor_bot_health())
        
        return self.application
    
    async def _start_resilient_polling(self):
        """Start polling with automatic recovery from network errors."""
        max_retries = 5
        base_delay = 5.0
        max_delay = 300.0  # 5 minutes max delay
        
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                logger.info(f"Starting Telegram polling (attempt {retry_count + 1}/{max_retries})")
                await self.application.updater.start_polling(
                    poll_interval=2.0,  # Check for updates every 2 seconds when polling fails
                    timeout=30,         # Timeout for getUpdates calls
                    read_timeout=40,    # Read timeout (should be > timeout)
                    connect_timeout=15, # Connection timeout
                    pool_timeout=10,    # Pool timeout
                    bootstrap_retries=3,  # Number of retries for initial connection
                    allowed_updates=None  # Allow all update types
                )
                
                # If we get here, polling started successfully
                retry_count = 0  # Reset retry count on success
                logger.info("Telegram polling started successfully")
                break
                
            except (NetworkError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"Failed to start Telegram polling after {max_retries} attempts: {e}")
                    raise
                
                # Calculate exponential backoff delay
                delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                logger.warning(f"Network error starting Telegram polling: {e}. Retrying in {delay:.1f}s (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(delay)
                
            except Exception as e:
                logger.error(f"Unexpected error starting Telegram polling: {e}")
                raise
    
    async def _recover_from_network_error(self):
        """Recover from network errors by restarting polling."""
        if not self.application or not self.application.updater:
            logger.warning("Cannot recover from network error: no application or updater available")
            return
            
        try:
            # Wait a moment for any in-flight requests to complete
            await asyncio.sleep(2.0)
            
            # Check if the updater is still running
            if self.application.updater.running:
                logger.info("Updater appears to be running, checking if polling is healthy...")
                
                # Try a simple test to see if the connection is working
                try:
                    await asyncio.wait_for(
                        self.application.bot.get_me(), 
                        timeout=10.0
                    )
                    logger.info("Bot API connection test successful, no recovery needed")
                    return
                except Exception as e:
                    logger.warning(f"Bot API connection test failed: {e}, attempting restart...")
            
            # Stop current polling if running
            if self.application.updater.running:
                logger.info("Stopping current polling before restart...")
                await self.application.updater.stop()
                await asyncio.sleep(1.0)  # Brief pause
            
            # Restart polling with resilience
            logger.info("Restarting Telegram polling after network error...")
            await self._start_resilient_polling()
            
        except Exception as e:
            logger.error(f"Failed to recover from network error: {e}")
            # Schedule another recovery attempt in case this one failed
            await asyncio.sleep(30.0)
            asyncio.create_task(self._recover_from_network_error())
    
    async def monitor_bot_health(self):
        """Monitor bot health and restart if necessary."""
        health_check_interval = 180  # Check every 3 minutes (reduced from 5)
        max_consecutive_failures = 3
        consecutive_failures = 0
        last_successful_check = None
        
        logger.info("Starting Telegram bot health monitoring...")
        
        while True:
            try:
                await asyncio.sleep(health_check_interval)
                
                # Comprehensive health check
                health_status = await self._perform_health_check()
                
                if health_status['healthy']:
                    if consecutive_failures > 0:
                        logger.info(f"Bot health recovered after {consecutive_failures} failures")
                    consecutive_failures = 0
                    last_successful_check = datetime.now()
                    
                    # Log periodic health status
                    if last_successful_check and (datetime.now() - last_successful_check).total_seconds() % 1800 < health_check_interval:  # Every 30 minutes
                        logger.info(f"Bot health check passed - Status: {health_status['status']}")
                else:
                    consecutive_failures += 1
                    logger.warning(f"Bot health check failed (attempt {consecutive_failures}/{max_consecutive_failures}): {health_status['status']}")
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"Bot failed health check {consecutive_failures} times, stopping monitoring")
                        # Attempt one final recovery before giving up
                        try:
                            await self._recover_from_network_error()
                        except Exception as e:
                            logger.error(f"Final recovery attempt failed: {e}")
                        break
                    else:
                        # Attempt recovery
                        try:
                            await self._recover_from_network_error()
                        except Exception as e:
                            logger.error(f"Health check recovery attempt failed: {e}")
                        
            except asyncio.CancelledError:
                logger.info("Bot health monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in bot health monitoring: {e}")
                consecutive_failures += 1
    
    async def _perform_health_check(self):
        """Perform a comprehensive health check of the bot."""
        if not self.application or not self.application.updater:
            return {'healthy': False, 'status': 'No application or updater available'}
        
        try:
            # Check 1: Is the updater running?
            if not self.application.updater.running:
                return {'healthy': False, 'status': 'Updater not running'}
            
            # Check 2: Can we make a simple API call?
            try:
                await asyncio.wait_for(
                    self.application.bot.get_me(), 
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                return {'healthy': False, 'status': 'API call timeout'}
            except Exception as e:
                return {'healthy': False, 'status': f'API call failed: {e}'}
            
            # Check 3: Are we receiving updates? (Check last update time if available)
            try:
                # This is a bit more complex as we need to track when we last received an update
                # For now, if the API call succeeded and updater is running, consider it healthy
                pass
            except Exception:
                pass
            
            return {'healthy': True, 'status': 'All checks passed'}
            
        except Exception as e:
            return {'healthy': False, 'status': f'Health check error: {e}'}
    
    async def stop_bot(self):
        """Stop the Telegram bot."""
        if self.application:
            logger.info("Stopping Telegram bot...")
            try:
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            except Exception as e:
                logger.warning(f"Error during bot shutdown: {e}")
        # Always release the singleton lock
        self._release_singleton_lock()


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
