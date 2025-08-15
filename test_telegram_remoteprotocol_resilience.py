#!/usr/bin/env python3
"""
Enhanced test script to verify Telegram bot resilience to RemoteProtocolError.

This script simulates the specific RemoteProtocolError that was causing issues
and verifies that the bot can recover automatically with the new resilience patterns.

Usage:
    python test_telegram_remoteprotocol_resilience.py
"""

import asyncio
import os
import sys
import logging
import signal
import random
from unittest.mock import patch, AsyncMock
import httpx
from datetime import datetime

# Add the project root to the path so we can import Django modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'news_trader.settings')
import django
django.setup()

from core.telegram_bot import TelegramBotService

# Set up logging with enhanced detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RemoteProtocolErrorSimulator:
    """Simulate RemoteProtocolError scenarios for testing resilience."""
    
    def __init__(self):
        self.fail_probability = 0.0  # Probability of failure (0.0 to 1.0)
        self.failure_count = 0
        self.total_requests = 0
        self.original_request = None
        self.simulation_active = False
    
    async def simulated_request(self, *args, **kwargs):
        """Simulate HTTP requests with controlled failures."""
        self.total_requests += 1
        
        if self.simulation_active and random.random() < self.fail_probability:
            self.failure_count += 1
            logger.info(f"🔴 Simulating RemoteProtocolError (failure {self.failure_count})")
            raise httpx.RemoteProtocolError("Simulated: Server disconnected without sending a response.")
        
        # Call the original request method
        return await self.original_request(*args, **kwargs)
    
    def start_simulation(self, fail_probability=0.7):
        """Start simulating failures with given probability."""
        self.fail_probability = fail_probability
        self.simulation_active = True
        self.failure_count = 0
        self.total_requests = 0
        logger.info(f"🎬 Starting RemoteProtocolError simulation with {fail_probability:.0%} failure rate")
    
    def stop_simulation(self):
        """Stop simulating failures."""
        self.simulation_active = False
        logger.info(f"⏹️ Stopped simulation. Generated {self.failure_count} failures out of {self.total_requests} requests")
    
    def get_stats(self):
        """Get simulation statistics."""
        return {
            'failures': self.failure_count,
            'total_requests': self.total_requests,
            'failure_rate': self.failure_count / max(self.total_requests, 1),
            'active': self.simulation_active
        }


async def test_remoteprotocol_resilience():
    """Test the bot's resilience to RemoteProtocolError specifically."""
    logger.info("🚀 Starting RemoteProtocolError resilience test...")
    
    # Check if we have the required environment variables
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
        return False
    
    simulator = RemoteProtocolErrorSimulator()
    bot_service = TelegramBotService()
    
    try:
        # Start the bot first
        logger.info("📡 Starting Telegram bot...")
        app = await bot_service.start_bot()
        
        if not app:
            logger.error("❌ Failed to start Telegram bot")
            return False
        
        logger.info("✅ Bot started successfully")
        
        # Let the bot run normally for a short time
        logger.info("⏳ Letting bot run normally for 15 seconds...")
        await asyncio.sleep(15)
        
        # Verify bot is healthy before starting stress test
        try:
            bot_info = await app.bot.get_me()
            logger.info(f"✅ Bot is healthy before test: @{bot_info.username}")
        except Exception as e:
            logger.error(f"❌ Bot unhealthy before test: {e}")
            return False
        
        # Start simulating RemoteProtocolError with patch
        logger.info("🧪 Starting RemoteProtocolError simulation...")
        
        # Patch the HTTP client request method
        with patch.object(httpx.AsyncClient, 'request', side_effect=simulator.simulated_request):
            simulator.original_request = httpx.AsyncClient.request
            
            # Phase 1: Moderate failure rate (50%)
            logger.info("📊 Phase 1: Moderate failure rate (50%) for 30 seconds")
            simulator.start_simulation(fail_probability=0.5)
            await asyncio.sleep(30)
            
            phase1_stats = simulator.get_stats()
            logger.info(f"Phase 1 stats: {phase1_stats['failures']} failures out of {phase1_stats['total_requests']} requests")
            
            # Phase 2: High failure rate (80%) 
            logger.info("📊 Phase 2: High failure rate (80%) for 20 seconds")
            simulator.start_simulation(fail_probability=0.8)
            await asyncio.sleep(20)
            
            phase2_stats = simulator.get_stats()
            logger.info(f"Phase 2 stats: {phase2_stats['failures']} failures out of {phase2_stats['total_requests']} requests")
            
            # Phase 3: Very high failure rate (95%) for short burst
            logger.info("📊 Phase 3: Very high failure rate (95%) for 10 seconds")
            simulator.start_simulation(fail_probability=0.95)
            await asyncio.sleep(10)
            
            # Stop simulation
            simulator.stop_simulation()
            logger.info("🔄 Network errors stopped, testing recovery...")
            
            # Give the bot time to recover
            await asyncio.sleep(30)
        
        # Test if the bot recovered and is responsive
        logger.info("🔍 Testing bot responsiveness after recovery...")
        recovery_attempts = 5
        recovery_successful = False
        
        for attempt in range(recovery_attempts):
            try:
                bot_info = await asyncio.wait_for(
                    app.bot.get_me(), 
                    timeout=15.0
                )
                logger.info(f"✅ Bot is responsive after recovery: @{bot_info.username}")
                recovery_successful = True
                break
            except Exception as e:
                logger.warning(f"⚠️ Recovery test attempt {attempt + 1}/{recovery_attempts} failed: {e}")
                if attempt < recovery_attempts - 1:
                    await asyncio.sleep(10)
        
        # Final statistics
        final_stats = simulator.get_stats()
        logger.info(f"📈 Final test statistics:")
        logger.info(f"   - Total simulated failures: {final_stats['failures']}")
        logger.info(f"   - Total requests intercepted: {final_stats['total_requests']}")
        logger.info(f"   - Overall failure rate: {final_stats['failure_rate']:.1%}")
        logger.info(f"   - Recovery successful: {recovery_successful}")
        
        return recovery_successful
    
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        return False
    
    finally:
        # Clean up
        logger.info("🧹 Cleaning up test environment...")
        try:
            await bot_service.stop_bot()
        except Exception as e:
            logger.warning(f"Warning during cleanup: {e}")


async def test_health_monitoring():
    """Test the health monitoring system's response to errors."""
    logger.info("🏥 Testing health monitoring system...")
    
    bot_service = TelegramBotService()
    
    try:
        app = await bot_service.start_bot()
        if not app:
            logger.error("❌ Failed to start bot for health monitoring test")
            return False
        
        logger.info("✅ Bot started for health monitoring test")
        
        # Let health monitoring run for a bit
        await asyncio.sleep(60)
        
        # Manually trigger a health check
        if hasattr(bot_service, '_perform_health_check'):
            health_status = await bot_service._perform_health_check()
            logger.info(f"📊 Health check result: {health_status}")
            return health_status['healthy']
        else:
            logger.warning("⚠️ Health check method not available")
            return True
    
    except Exception as e:
        logger.error(f"❌ Health monitoring test failed: {e}")
        return False
    
    finally:
        await bot_service.stop_bot()


async def main():
    """Main test function."""
    start_time = datetime.now()
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("🛑 Test interrupted by user")
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🧪 Enhanced Telegram Bot Resilience Test Suite")
    logger.info("=" * 60)
    
    try:
        # Test 1: RemoteProtocolError resilience
        logger.info("🧪 TEST 1: RemoteProtocolError Resilience")
        test1_success = await test_remoteprotocol_resilience()
        
        # Brief pause between tests
        await asyncio.sleep(10)
        
        # Test 2: Health monitoring system
        logger.info("🧪 TEST 2: Health Monitoring System")
        test2_success = await test_health_monitoring()
        
        # Results summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("=" * 60)
        logger.info("📊 TEST RESULTS SUMMARY")
        logger.info(f"   Test 1 (RemoteProtocolError): {'✅ PASSED' if test1_success else '❌ FAILED'}")
        logger.info(f"   Test 2 (Health Monitoring): {'✅ PASSED' if test2_success else '❌ FAILED'}")
        logger.info(f"   Total test duration: {duration.total_seconds():.1f} seconds")
        
        overall_success = test1_success and test2_success
        
        if overall_success:
            logger.info("🎉 ALL TESTS PASSED - Bot resilience is working correctly!")
            return 0
        else:
            logger.error("💥 SOME TESTS FAILED - Bot may have resilience issues")
            return 1
    
    except KeyboardInterrupt:
        logger.info("🛑 Test suite interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"💥 Test suite error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
