import atexit
import threading
from typing import Optional, Tuple, Any

from playwright.sync_api import sync_playwright, Browser


_playwright_instance = None  # type: Optional[object]
_browser_instance = None  # type: Optional[Browser]
_browser_lock = threading.Lock()


def _launch_browser() -> tuple[Any, Browser]:
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
        ],
    )
    return playwright, browser


def get_browser() -> Browser:
    global _playwright_instance, _browser_instance
    if _browser_instance is not None:
        return _browser_instance
    with _browser_lock:
        if _browser_instance is None:
            _playwright_instance, _browser_instance = _launch_browser()
    return _browser_instance


def _shutdown():
    global _playwright_instance, _browser_instance
    try:
        if _browser_instance is not None:
            try:
                _browser_instance.close()
            except Exception:
                pass
        if _playwright_instance is not None:
            try:
                _playwright_instance.stop()
            except Exception:
                pass
    finally:
        _browser_instance = None
        _playwright_instance = None


atexit.register(_shutdown)


