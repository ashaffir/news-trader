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
import random
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
            # Reduced lock timeout from 120s to 60s for faster recovery
            ok = client.set(key, value, nx=True, ex=60)
            if ok:
                self._lock = (client, key, value)
                # Start background refresher
                self._lock_stop.clear()
                self._lock_thread = threading.Thread(target=self._refresh_lock_loop, daemon=True)
                self._lock_thread.start()
                return True
            else:
                # Check if the existing lock is stale (older than 2 minutes)
                existing_ttl = client.ttl(key)
                if existing_ttl == -1:  # No expiry set (shouldn't happen but handle it)
                    logger.warning("Found Redis lock with no expiry, clearing it")
                    client.delete(key)
                    # Try again after clearing stale lock
                    ok = client.set(key, value, nx=True, ex=60)
                    if ok:
                        self._lock = (client, key, value)
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
                    client.expire(key, 60)  # Consistent with initial timeout
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
                
                # For RemoteProtocolError and ConnectError, be more aggressive in recovery
                if isinstance(err, (httpx.RemoteProtocolError, httpx.ConnectError)):
                    logger.warning(f"Critical network error detected: {type(err).__name__}. Initiating immediate recovery...")
                    asyncio.create_task(self._recover_from_critical_network_error())
                else:
                    # For other NetworkErrors, use standard recovery
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
                    "connect_timeout": 20.0,   # Increased connection timeout
                    "read_timeout": 90.0,      # Increased read timeout for long polling
                    "write_timeout": 45.0,     # Increased write timeout
                    "pool_timeout": 15.0,      # Increased pool timeout
                }
                
                # Force HTTP/1.1 to avoid HTTP/2 connection issues
                if HTTPVersion is not None:
                    request_kwargs["http_version"] = HTTPVersion.HTTP_1_1  # type: ignore
                else:
                    # Some PTB versions accept a string
                    request_kwargs["http_version"] = "1.1"
                    
                logger.info("Configuring Telegram bot with enhanced HTTP settings for maximum resilience")
                builder = builder.request(HTTPXRequest(**request_kwargs))
            
            # Configure polling with more conservative settings for better resilience
            builder = builder.get_updates_connect_timeout(20)
            builder = builder.get_updates_read_timeout(90)  
            builder = builder.get_updates_write_timeout(45)
            builder = builder.get_updates_pool_timeout(15)
            
            # Configure reasonable polling timeout
            if hasattr(builder, "get_updates_request_timeout"):
                builder = builder.get_updates_request_timeout(75)
                
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
        """Start polling with automatic recovery from network errors and circuit breaker pattern."""
        max_retries = 7  # Increased retry attempts
        base_delay = 3.0  # Reduced initial delay for faster recovery
        max_delay = 180.0  # Reduced max delay (3 minutes)
        
        retry_count = 0
        consecutive_failures = 0
        circuit_breaker_threshold = 3
        
        while retry_count < max_retries:
            try:
                # Circuit breaker logic: if we have too many consecutive failures, wait longer
                if consecutive_failures >= circuit_breaker_threshold:
                    circuit_delay = min(30.0 * consecutive_failures, 300.0)  # Progressive delay up to 5 minutes
                    logger.warning(f"Circuit breaker activated due to {consecutive_failures} consecutive failures. Waiting {circuit_delay:.1f}s before retry...")
                    await asyncio.sleep(circuit_delay)
                
                logger.info(f"Starting Telegram polling (attempt {retry_count + 1}/{max_retries}, consecutive failures: {consecutive_failures})")
                
                # Enhanced polling configuration for better resilience
                await self.application.updater.start_polling(
                    poll_interval=1.5,    # Slightly reduced poll interval for faster detection
                    timeout=45,           # Increased timeout for getUpdates calls  
                    read_timeout=60,      # Increased read timeout
                    connect_timeout=20,   # Increased connection timeout
                    pool_timeout=15,      # Increased pool timeout
                    bootstrap_retries=5,  # Increased bootstrap retries
                    allowed_updates=None, # Allow all update types
                )
                
                # If we get here, polling started successfully
                retry_count = 0
                consecutive_failures = 0  # Reset consecutive failures on success
                logger.info("Telegram polling started successfully - circuit breaker reset")
                
                # Wait a moment to ensure polling is stable before returning
                await asyncio.sleep(3.0)
                
                # Final verification
                if self.application.updater.running:
                    logger.info("Polling stability verified")
                    break
                else:
                    raise Exception("Polling failed to maintain stable state")
                
            except (NetworkError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                retry_count += 1
                consecutive_failures += 1
                
                if retry_count >= max_retries:
                    logger.error(f"Failed to start Telegram polling after {max_retries} attempts and {consecutive_failures} consecutive failures: {e}")
                    # Reset circuit breaker for next attempt
                    consecutive_failures = 0
                    raise
                
                # Calculate exponential backoff delay with jitter to avoid thundering herd
                jitter = random.uniform(0.8, 1.2)  # Add 20% jitter
                delay = min(base_delay * (2 ** (retry_count - 1)) * jitter, max_delay)
                
                logger.warning(f"Network error starting Telegram polling: {type(e).__name__}: {e}. "
                             f"Retrying in {delay:.1f}s (attempt {retry_count}/{max_retries}, "
                             f"consecutive failures: {consecutive_failures})")
                await asyncio.sleep(delay)
                
            except Exception as e:
                retry_count += 1
                consecutive_failures += 1
                logger.error(f"Unexpected error starting Telegram polling: {type(e).__name__}: {e}")
                
                if retry_count >= max_retries:
                    raise
                
                # For unexpected errors, use a fixed shorter delay
                await asyncio.sleep(10.0)
        
        # If we exit the loop without success, that's an error
        if retry_count >= max_retries:
            raise Exception(f"Exhausted all {max_retries} polling start attempts")
    
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
    
    async def _recover_from_critical_network_error(self):
        """Recover from critical network errors (RemoteProtocolError, ConnectError) with more aggressive approach."""
        if not self.application:
            logger.warning("Cannot recover from critical network error: no application available")
            return
            
        # Use exponential backoff for critical errors
        max_attempts = 5
        base_delay = 3.0
        max_delay = 120.0
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Critical network error recovery attempt {attempt + 1}/{max_attempts}")
                
                # Force stop the updater regardless of state
                if self.application.updater:
                    try:
                        logger.info("Force stopping updater due to critical network error...")
                        await self.application.updater.stop()
                        await asyncio.sleep(2.0)  # Give it time to fully stop
                    except Exception as e:
                        logger.warning(f"Error stopping updater: {e}")
                
                # Test basic connectivity before attempting restart
                try:
                    logger.info("Testing basic connectivity to Telegram API...")
                    await asyncio.wait_for(
                        self.application.bot.get_me(), 
                        timeout=15.0
                    )
                    logger.info("Basic connectivity test passed")
                except Exception as e:
                    logger.warning(f"Basic connectivity test failed: {e}")
                    # Continue with restart anyway
                
                # Restart polling with increased resilience settings
                logger.info("Restarting polling with enhanced resilience...")
                await self._start_resilient_polling()
                
                # Verify the restart was successful
                await asyncio.sleep(5.0)
                if self.application.updater and self.application.updater.running:
                    try:
                        await asyncio.wait_for(
                            self.application.bot.get_me(), 
                            timeout=10.0
                        )
                        logger.info("Critical network error recovery successful!")
                        return
                    except Exception as e:
                        logger.warning(f"Post-recovery verification failed: {e}")
                        raise e
                else:
                    raise Exception("Updater not running after restart")
                
            except Exception as e:
                delay = min(base_delay * (2 ** attempt), max_delay)
                if attempt < max_attempts - 1:
                    logger.warning(f"Critical recovery attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All critical recovery attempts failed: {e}")
                    # As a last resort, schedule standard recovery after a longer delay
                    await asyncio.sleep(60.0)
                    asyncio.create_task(self._recover_from_network_error())
    
    async def monitor_bot_health(self):
        """Monitor bot health and restart if necessary with enhanced resilience."""
        health_check_interval = 120  # Check every 2 minutes for faster detection
        max_consecutive_failures = 4  # Allow one more failure before giving up
        consecutive_failures = 0
        last_successful_check = None
        critical_error_count = 0  # Track critical errors separately
        
        logger.info("Starting enhanced Telegram bot health monitoring...")
        
        while True:
            try:
                await asyncio.sleep(health_check_interval)
                
                # Comprehensive health check
                health_status = await self._perform_health_check()
                
                if health_status['healthy']:
                    if consecutive_failures > 0:
                        logger.info(f"Bot health recovered after {consecutive_failures} failures")
                    consecutive_failures = 0
                    critical_error_count = 0  # Reset critical error count on success
                    last_successful_check = datetime.now()
                    
                    # Log periodic health status (every 20 minutes instead of 30)
                    if last_successful_check and (datetime.now() - last_successful_check).total_seconds() % 1200 < health_check_interval:
                        logger.info(f"Bot health check passed - Status: {health_status['status']}")
                        
                else:
                    consecutive_failures += 1
                    
                    # Check if this is a critical network error
                    is_critical = any(keyword in health_status['status'].lower() 
                                    for keyword in ['remoteprotocolerror', 'connecterror', 'timeout'])
                    
                    if is_critical:
                        critical_error_count += 1
                        logger.warning(f"Critical health check failure detected (attempt {consecutive_failures}/{max_consecutive_failures}, "
                                     f"critical errors: {critical_error_count}): {health_status['status']}")
                        
                        # For critical errors, use aggressive recovery immediately
                        if critical_error_count >= 2:  # After 2 critical errors, be more aggressive
                            logger.warning("Multiple critical errors detected, using aggressive recovery...")
                            try:
                                await self._recover_from_critical_network_error()
                            except Exception as e:
                                logger.error(f"Critical recovery attempt failed: {e}")
                        else:
                            # First critical error, try standard recovery
                            try:
                                await self._recover_from_network_error()
                            except Exception as e:
                                logger.error(f"Standard recovery attempt failed: {e}")
                    else:
                        logger.warning(f"Bot health check failed (attempt {consecutive_failures}/{max_consecutive_failures}): {health_status['status']}")
                        # For non-critical errors, use standard recovery
                        try:
                            await self._recover_from_network_error()
                        except Exception as e:
                            logger.error(f"Health check recovery attempt failed: {e}")
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"Bot failed health check {consecutive_failures} times, attempting final recovery...")
                        # One final aggressive recovery attempt before giving up
                        try:
                            await self._recover_from_critical_network_error()
                            # Give it some time to stabilize
                            await asyncio.sleep(30)
                            # Reset counters and continue monitoring
                            consecutive_failures = 0
                            critical_error_count = 0
                            logger.info("Final recovery attempt completed, resuming monitoring...")
                        except Exception as e:
                            logger.error(f"Final recovery attempt failed: {e}")
                            logger.error("Bot monitoring will continue but bot may be in degraded state")
                            # Don't break - keep monitoring in case the issue resolves
                            consecutive_failures = 0  # Reset to avoid infinite stopping
                        
            except asyncio.CancelledError:
                logger.info("Bot health monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in bot health monitoring: {e}")
                consecutive_failures += 1
    
    async def _perform_health_check(self):
        """Perform a comprehensive health check of the bot with enhanced error detection."""
        if not self.application or not self.application.updater:
            return {'healthy': False, 'status': 'No application or updater available'}
        
        try:
            # Check 1: Is the updater running?
            if not self.application.updater.running:
                return {'healthy': False, 'status': 'Updater not running'}
            
            # Check 2: Can we make a simple API call with retry logic?
            api_test_attempts = 2
            last_api_error = None
            
            for attempt in range(api_test_attempts):
                try:
                    await asyncio.wait_for(
                        self.application.bot.get_me(), 
                        timeout=12.0  # Reduced timeout for faster detection
                    )
                    break  # Success
                except asyncio.TimeoutError as e:
                    last_api_error = f'API call timeout (attempt {attempt + 1})'
                    if attempt < api_test_attempts - 1:
                        await asyncio.sleep(2.0)  # Brief pause before retry
                    continue
                except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
                    # These are critical network errors that we want to detect quickly
                    return {'healthy': False, 'status': f'Critical network error: {type(e).__name__}: {e}'}
                except Exception as e:
                    last_api_error = f'API call failed: {type(e).__name__}: {e}'
                    if attempt < api_test_attempts - 1:
                        await asyncio.sleep(2.0)  # Brief pause before retry
                    continue
            else:
                # All attempts failed
                return {'healthy': False, 'status': last_api_error or 'API call failed after all attempts'}
            
            # Check 3: Validate updater state more thoroughly
            try:
                # Check if the updater has any indication of network issues
                if hasattr(self.application.updater, '_running'):
                    # Additional state validation if available
                    pass
                    
                # For now, if API call succeeded and updater is running, consider it healthy
                # In the future, we could add more sophisticated checks like:
                # - Time since last update received
                # - HTTP connection pool status
                # - Error rate monitoring
                
            except Exception as e:
                logger.debug(f"Additional health check failed (non-critical): {e}")
            
            return {'healthy': True, 'status': 'All checks passed'}
            
        except Exception as e:
            error_type = type(e).__name__
            # Classify the error type for better handling
            if 'RemoteProtocolError' in error_type or 'ConnectError' in error_type:
                return {'healthy': False, 'status': f'Critical network error in health check: {error_type}: {e}'}
            else:
                return {'healthy': False, 'status': f'Health check error: {error_type}: {e}'}
    
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
