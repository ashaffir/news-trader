"""
Thread-aware Managed Browser Pool for Playwright Chrome processes.
Prevents accumulation of Chrome processes while maintaining efficiency.
Uses thread-local storage to ensure browser instances are thread-safe.
"""
import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any
from dataclasses import dataclass
from queue import Queue, Empty
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


@dataclass
class BrowserInstance:
    """Container for browser instance with metadata"""
    browser: Browser
    playwright: Any
    created_at: datetime
    last_used: datetime
    usage_count: int = 0
    
    def is_expired(self, max_age_minutes: int = 30, max_usage: int = 100) -> bool:
        """Check if browser instance should be retired"""
        age_expired = datetime.now() - self.created_at > timedelta(minutes=max_age_minutes)
        usage_expired = self.usage_count >= max_usage
        return age_expired or usage_expired


class ThreadLocalBrowserPool:
    """
    Thread-local browser pool that manages Chrome process lifecycle per thread.
    
    Features:
    - Thread-local browser instances (no cross-thread sharing)
    - Limited pool size per thread to prevent Chrome process accumulation
    - Browser retirement based on age and usage
    - Automatic cleanup of expired browsers
    - Graceful shutdown handling
    """
    
    def __init__(self, 
                 max_browsers_per_thread: int = 2,
                 max_browser_age_minutes: int = 30,
                 max_browser_usage: int = 50):
        self.max_browsers_per_thread = max_browsers_per_thread
        self.max_browser_age_minutes = max_browser_age_minutes
        self.max_browser_usage = max_browser_usage
        
        # Thread-local storage for browser pools
        self._thread_local = threading.local()
        self._global_lock = threading.RLock()  # Only for global operations
        
        # Browser launch configuration
        self._browser_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows", 
            "--disable-renderer-backgrounding",
            "--no-first-run",
            "--disable-extensions",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-background-networking",
            "--disable-sync",
            "--no-default-browser-check",
            "--disable-client-side-phishing-detection",
        ]
        
        logger.info(f"Initialized ThreadLocalBrowserPool: max_per_thread={max_browsers_per_thread}, "
                   f"max_age={max_browser_age_minutes}min, max_usage={max_browser_usage}")
    
    def _get_thread_pool(self):
        """Get or create thread-local browser pool data"""
        if not hasattr(self._thread_local, 'pool'):
            self._thread_local.pool = Queue(maxsize=self.max_browsers_per_thread)
            self._thread_local.active_browsers = {}
            self._thread_local.thread_id = threading.get_ident()
            self._thread_local.shutdown = False  # Thread-local shutdown flag
            logger.debug(f"Initialized thread-local browser pool for thread {self._thread_local.thread_id}")
        return self._thread_local
    
    def _create_browser_instance(self) -> BrowserInstance:
        """Create a new browser instance for current thread"""
        thread_pool = self._get_thread_pool()
        thread_id = thread_pool.thread_id
        
        try:
            logger.info(f"Creating new Playwright browser instance for thread {thread_id}")
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                args=self._browser_args
            )
            
            instance = BrowserInstance(
                browser=browser,
                playwright=playwright,
                created_at=datetime.now(),
                last_used=datetime.now()
            )
            
            instance_id = id(instance)
            thread_pool.active_browsers[instance_id] = instance
                
            logger.info(f"Created browser instance {instance_id} for thread {thread_id}")
            return instance
            
        except Exception as e:
            logger.error(f"Failed to create browser instance for thread {thread_id}: {e}")
            raise
    
    def _cleanup_browser_instance(self, instance: BrowserInstance):
        """Safely cleanup a browser instance"""
        thread_pool = self._get_thread_pool()
        instance_id = id(instance)
        thread_id = thread_pool.thread_id
        
        logger.info(f"Cleaning up browser instance {instance_id} for thread {thread_id}")
        
        try:
            if instance.browser:
                instance.browser.close()
            if instance.playwright:
                instance.playwright.stop()
                
            thread_pool.active_browsers.pop(instance_id, None)
                
            logger.info(f"Successfully cleaned up browser instance {instance_id} for thread {thread_id}")
            
        except Exception as e:
            logger.warning(f"Error cleaning up browser instance {instance_id} for thread {thread_id}: {e}")
    
    def _cleanup_expired_browsers(self):
        """Remove expired browsers from the current thread's pool"""
        thread_pool = self._get_thread_pool()
        if thread_pool.shutdown:
            return
            
        expired_instances = []
        
        for instance_id, instance in list(thread_pool.active_browsers.items()):
            if instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
                expired_instances.append(instance)
        
        for instance in expired_instances:
            logger.info(f"Retiring expired browser instance {id(instance)} "
                       f"(age: {datetime.now() - instance.created_at}, "
                       f"usage: {instance.usage_count})")
            self._cleanup_browser_instance(instance)
    
    def get_browser(self) -> BrowserInstance:
        """Get a browser instance from the current thread's pool"""
        thread_pool = self._get_thread_pool()
        if thread_pool.shutdown:
            raise RuntimeError(f"Browser pool for thread {thread_pool.thread_id} is shutdown")
        
        thread_id = thread_pool.thread_id
        
        # Clean up expired browsers first
        self._cleanup_expired_browsers()
        
        # Try to get an existing browser from thread-local pool
        try:
            instance = thread_pool.pool.get_nowait()
            
            # Check if this instance is still valid
            if not instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
                instance.last_used = datetime.now()
                instance.usage_count += 1
                logger.debug(f"Reusing browser instance {id(instance)} in thread {thread_id} "
                           f"(usage: {instance.usage_count})")
                return instance
            else:
                # Instance is expired, clean it up and create a new one
                logger.info(f"Retrieved expired browser instance {id(instance)} from thread {thread_id}, creating new one")
                self._cleanup_browser_instance(instance)
                
        except Empty:
            # Pool is empty, check if we can create a new browser
            if len(thread_pool.active_browsers) >= self.max_browsers_per_thread:
                logger.warning(f"Thread {thread_id} browser pool at capacity ({self.max_browsers_per_thread}), "
                             f"waiting for available browser")
                # Wait a bit and try again
                time.sleep(0.1)
                try:
                    instance = thread_pool.pool.get(timeout=5.0)  # Shorter timeout for thread-local
                    instance.last_used = datetime.now()
                    instance.usage_count += 1
                    return instance
                except Empty:
                    raise RuntimeError(f"No browser available in thread {thread_id} within 5s timeout")
        
        # Create new browser instance for this thread
        return self._create_browser_instance()
    
    def return_browser(self, instance: BrowserInstance):
        """Return a browser instance to the current thread's pool"""
        thread_pool = self._get_thread_pool()
        if thread_pool.shutdown:
            self._cleanup_browser_instance(instance)
            return
        
        thread_id = thread_pool.thread_id
        
        try:
            # Check if instance is still valid
            if instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
                logger.info(f"Browser instance {id(instance)} in thread {thread_id} expired, cleaning up instead of returning")
                self._cleanup_browser_instance(instance)
                return
            
            # Return to thread-local pool if there's space
            thread_pool.pool.put_nowait(instance)
            logger.debug(f"Returned browser instance {id(instance)} to thread {thread_id} pool")
            
        except Exception as e:
            logger.warning(f"Failed to return browser instance {id(instance)} to thread {thread_id} pool: {e}")
            self._cleanup_browser_instance(instance)
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get current thread's pool statistics"""
        try:
            thread_pool = self._get_thread_pool()
            thread_id = thread_pool.thread_id
            
            active_count = len(thread_pool.active_browsers)
            pool_size = thread_pool.pool.qsize()
            
            return {
                "thread_id": thread_id,
                "active_browsers": active_count,
                "available_in_pool": pool_size,
                "max_browsers_per_thread": self.max_browsers_per_thread,
                "in_use": active_count - pool_size,
                "pool_utilization": f"{(active_count / self.max_browsers_per_thread) * 100:.1f}%" if self.max_browsers_per_thread > 0 else "0%"
            }
        except Exception as e:
            return {
                "error": str(e),
                "thread_id": threading.get_ident()
            }
    
    def shutdown(self):
        """Shutdown the current thread's browser pool and cleanup all instances"""
        try:
            thread_pool = self._get_thread_pool()
            thread_id = thread_pool.thread_id
            
            logger.info(f"Shutting down ThreadLocalBrowserPool for thread {thread_id}")
            thread_pool.shutdown = True  # Set thread-local shutdown flag
            
            # Clean up all active browsers in this thread
            for instance in list(thread_pool.active_browsers.values()):
                self._cleanup_browser_instance(instance)
            
            # Clear the thread-local pool
            while not thread_pool.pool.empty():
                try:
                    thread_pool.pool.get_nowait()
                except Empty:
                    break
                    
            logger.info(f"ThreadLocalBrowserPool shutdown complete for thread {thread_id}")
        except Exception as e:
            thread_id = threading.get_ident()
            logger.warning(f"Error during thread {thread_id} browser pool shutdown: {e}")


# Global browser pool instance
_browser_pool: Optional[ThreadLocalBrowserPool] = None
_pool_lock = threading.Lock()


def get_browser_pool() -> ThreadLocalBrowserPool:
    """Get or create the global thread-local browser pool"""
    global _browser_pool
    
    if _browser_pool is None:
        with _pool_lock:
            if _browser_pool is None:
                _browser_pool = ThreadLocalBrowserPool()
                # Note: No atexit registration - let threads manage their own cleanup
    
    return _browser_pool


@contextmanager
def get_managed_browser_context():
    """Context manager for browser operations with proper pool management"""
    pool = get_browser_pool()
    browser_instance = None
    context = None
    
    try:
        browser_instance = pool.get_browser()
        context = browser_instance.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 2000},
        )
        yield context
        
    except Exception as e:
        logger.error(f"Error in managed browser context: {e}")
        raise
        
    finally:
        if context:
            try:
                context.close()
            except Exception as e:
                logger.warning(f"Error closing browser context: {e}")
        
        if browser_instance:
            pool.return_browser(browser_instance)


@contextmanager
def get_managed_browser_page():
    """Context manager for browser page operations with proper pool management"""
    page = None
    try:
        with get_managed_browser_context() as context:
            page = context.new_page()
            yield page
    finally:
        if page:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"Error closing browser page: {e}")


def get_browser_pool_stats() -> Dict[str, Any]:
    """Get browser pool statistics for monitoring"""
    try:
        pool = get_browser_pool()
        return pool.get_pool_stats()
    except Exception as e:
        logger.error(f"Error getting browser pool stats: {e}")
        return {"error": str(e)}


def cleanup_browser_pool():
    """Manually cleanup the current thread's browser pool"""
    try:
        pool = get_browser_pool()
        pool.shutdown()
        logger.info(f"Cleaned up browser pool for thread {threading.get_ident()}")
    except Exception as e:
        logger.error(f"Error during manual browser pool cleanup: {e}")
