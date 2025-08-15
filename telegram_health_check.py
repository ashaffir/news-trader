#!/usr/bin/env python3
"""
Simple health check script for the Telegram bot.

This script checks if the Telegram bot is running and responsive.
Exit code 0 = healthy, non-zero = unhealthy.

Usage:
    python telegram_health_check.py
"""

import asyncio
import os
import sys
import logging
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'news_trader.settings')
import django
django.setup()

from core.telegram_bot import get_bot_service

# Suppress verbose logging for health checks
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def check_bot_health():
    """Check if the Telegram bot is healthy."""
    bot_service = get_bot_service()
    
    if not bot_service:
        print("❌ Bot service not running")
        return False
    
    if not bot_service.application:
        print("❌ Bot application not initialized")
        return False
    
    if not bot_service.application.updater:
        print("❌ Bot updater not available")
        return False
    
    if not bot_service.application.updater.running:
        print("❌ Bot updater not running")
        return False
    
    # Try to make a simple API call to verify connectivity with retries
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            bot_info = await asyncio.wait_for(
                bot_service.application.bot.get_me(), 
                timeout=12.0
            )
            print(f"✅ Bot is healthy: @{bot_info.username}")
            return True
        except asyncio.TimeoutError:
            print(f"⚠️ Bot API call timed out (attempt {attempt + 1}/{max_attempts})")
            if attempt < max_attempts - 1:
                await asyncio.sleep(3.0)  # Brief pause before retry
                continue
            print("❌ Bot API call timed out after all attempts")
            return False
        except Exception as e:
            error_type = type(e).__name__
            if 'RemoteProtocolError' in error_type or 'ConnectError' in error_type:
                print(f"❌ Critical network error detected: {error_type}: {e}")
                return False
            else:
                print(f"⚠️ Bot API call failed (attempt {attempt + 1}/{max_attempts}): {error_type}: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(3.0)  # Brief pause before retry
                    continue
                print("❌ Bot API call failed after all attempts")
                return False
    
    return False


async def main():
    """Main health check function."""
    try:
        is_healthy = await check_bot_health()
        return 0 if is_healthy else 1
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
