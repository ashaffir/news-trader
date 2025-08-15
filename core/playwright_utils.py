import atexit
import threading
import logging
from typing import Optional, Tuple, Any
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Thread-local storage for browser instances
_thread_local = threading.local()


def _get_thread_browser_data():
    """Get or create thread-local browser data"""
    if not hasattr(_thread_local, 'playwright'):
        _thread_local.playwright = None
        _thread_local.browser = None
        _thread_local.thread_id = threading.get_ident()
    return _thread_local


def _launch_browser_for_thread() -> tuple[Any, Browser]:
    """Launch a new browser instance for the current thread"""
    logger.info(f"Launching new Playwright browser for thread {threading.get_ident()}")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--no-first-run",
            "--disable-extensions",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
        ],
    )
    return playwright, browser


def get_browser() -> Browser:
    """Get browser instance for the current thread"""
    thread_data = _get_thread_browser_data()
    
    if thread_data.browser is None:
        try:
            thread_data.playwright, thread_data.browser = _launch_browser_for_thread()
            logger.info(f"Browser instance created for thread {thread_data.thread_id}")
        except Exception as e:
            logger.error(f"Failed to create browser instance for thread {threading.get_ident()}: {e}")
            raise
    
    return thread_data.browser


@contextmanager
def get_browser_context():
    """Context manager for browser operations that ensures proper cleanup"""
    browser = None
    context = None
    try:
        browser = get_browser()
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 2000},
        )
        yield context
    except Exception as e:
        logger.error(f"Error in browser context: {e}")
        raise
    finally:
        if context:
            try:
                context.close()
            except Exception as e:
                logger.warning(f"Error closing browser context: {e}")


@contextmanager 
def get_browser_page():
    """Context manager for browser page operations"""
    page = None
    try:
        with get_browser_context() as context:
            page = context.new_page()
            yield page
    finally:
        if page:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"Error closing browser page: {e}")


def _cleanup_thread_browser():
    """Clean up browser instances for the current thread"""
    thread_data = _get_thread_browser_data()
    thread_id = threading.get_ident()
    
    try:
        if thread_data.browser is not None:
            try:
                thread_data.browser.close()
                logger.info(f"Closed browser for thread {thread_id}")
            except Exception as e:
                logger.warning(f"Error closing browser for thread {thread_id}: {e}")
            finally:
                thread_data.browser = None
                
        if thread_data.playwright is not None:
            try:
                thread_data.playwright.stop()
                logger.info(f"Stopped Playwright for thread {thread_id}")
            except Exception as e:
                logger.warning(f"Error stopping Playwright for thread {thread_id}: {e}")
            finally:
                thread_data.playwright = None
                
    except Exception as e:
        logger.error(f"Error during thread browser cleanup: {e}")


def _global_shutdown():
    """Global shutdown for all browser instances"""
    try:
        _cleanup_thread_browser()
    except Exception as e:
        logger.error(f"Error during global browser shutdown: {e}")


# Register cleanup at exit
atexit.register(_global_shutdown)


