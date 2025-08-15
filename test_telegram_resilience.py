#!/usr/bin/env python3
"""
Test script to verify Telegram bot resilience to network errors.

This script simulates network connectivity issues by:
1. Starting the bot
2. Simulating network errors
3. Verifying the bot recovers automatically

Usage:
    python test_telegram_resilience.py
"""

import asyncio
import os
import sys
import logging
import signal
from unittest.mock import patch
import httpx

# Add the project root to the path so we can import Django modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'news_trader.settings')
import django
django.setup()

from core.telegram_bot import TelegramBotService

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NetworkSimulator:
    """Simulate network connectivity issues."""
    
    def __init__(self):
        self.fail_requests = False
        self.original_request = None
    
    async def failing_request(self, *args, **kwargs):
        """Simulate a failing HTTP request."""
        if self.fail_requests:
            logger.info("Simulating network failure...")
            raise httpx.RemoteProtocolError("Simulated: Server disconnected without sending a response.")
        return await self.original_request(*args, **kwargs)
    
    def start_failure_simulation(self):
        """Start simulating network failures."""
        logger.info("Starting network failure simulation...")
        self.fail_requests = True
    
    def stop_failure_simulation(self):
        """Stop simulating network failures."""
        logger.info("Stopping network failure simulation...")
        self.fail_requests = False


async def test_bot_resilience():
    """Test the bot's resilience to network errors."""
    logger.info("Starting Telegram bot resilience test...")
    
    # Check if we have the required environment variables
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return False
    
    simulator = NetworkSimulator()
    bot_service = TelegramBotService()
    
    try:
        # Start the bot
        logger.info("Starting Telegram bot...")
        app = await bot_service.start_bot()
        
        if not app:
            logger.error("Failed to start Telegram bot")
            return False
        
        logger.info("Bot started successfully")
        
        # Let the bot run normally for a few seconds
        logger.info("Letting bot run normally for 10 seconds...")
        await asyncio.sleep(10)
        
        # Simulate network connectivity issues
        logger.info("Simulating network connectivity issues...")
        
        # Patch the HTTP requests to simulate failures
        with patch.object(httpx.AsyncClient, 'request', side_effect=simulator.failing_request):
            simulator.original_request = httpx.AsyncClient.request
            
            # Simulate failures for 30 seconds
            simulator.start_failure_simulation()
            await asyncio.sleep(30)
            
            # Stop simulating failures and see if bot recovers
            simulator.stop_failure_simulation()
            logger.info("Network restored, testing recovery...")
            await asyncio.sleep(30)
        
        # Test if the bot is still responsive
        logger.info("Testing bot responsiveness...")
        try:
            bot_info = await app.bot.get_me()
            logger.info(f"Bot is responsive: {bot_info.username}")
            return True
        except Exception as e:
            logger.error(f"Bot is not responsive after recovery: {e}")
            return False
    
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False
    
    finally:
        # Clean up
        logger.info("Stopping bot...")
        await bot_service.stop_bot()


async def main():
    """Main test function."""
    success = False
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Test interrupted by user")
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = await test_bot_resilience()
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test error: {e}")
    
    if success:
        logger.info("✅ Bot resilience test PASSED")
        return 0
    else:
        logger.error("❌ Bot resilience test FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
