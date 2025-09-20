"""
Thread-aware Managed Browser Pool for Playwright Chrome processes.
Prevents accumulation of Chrome processes while maintaining efficiency.
Uses thread-local storage to ensure browser instances are thread-safe.

This module now delegates to `scraper.services` to avoid duplication.
"""
import logging
from contextlib import contextmanager
from typing import Optional, Tuple, Any, Dict

from scraper.services.pool import get_browser_pool as _get_pool
from scraper.services.context import (
	get_managed_browser_context as _svc_get_ctx,
	get_managed_browser_context_with_state as _svc_get_ctx_state,
	get_managed_browser_page as _svc_get_page,
)

logger = logging.getLogger(__name__)


def get_browser_pool():
	return _get_pool()


@contextmanager
def get_managed_browser_context():
	with _svc_get_ctx() as ctx:
		yield ctx


@contextmanager
def get_managed_browser_context_with_state(storage_state: dict | None = None):
	with _svc_get_ctx_state(storage_state=storage_state) as ctx:
		yield ctx


@contextmanager
def get_managed_browser_page():
	with _svc_get_page() as page:
		yield page


def get_browser_pool_stats() -> Dict[str, Any]:
	try:
		pool = _get_pool()
		return pool.get_pool_stats()
	except Exception as e:
		logger.error(f"Error getting browser pool stats: {e}")
		return {"error": str(e)}


def cleanup_browser_pool():
	try:
		pool = _get_pool()
		pool.shutdown()
		logger.info("Cleaned up browser pool for current thread")
	except Exception as e:
		logger.error(f"Error during manual browser pool cleanup: {e}")
