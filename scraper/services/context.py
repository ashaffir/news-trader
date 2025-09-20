import logging
from contextlib import contextmanager
from typing import Any, Dict

from playwright.sync_api import BrowserContext, Page

from .pool import get_browser_pool

logger = logging.getLogger(__name__)


@contextmanager
def get_managed_browser_context(extra_context_kwargs: Dict[str, Any] | None = None):
	pool = get_browser_pool()
	browser_instance = None
	context: BrowserContext | None = None
	try:
		browser_instance = pool.get_browser()
		kwargs = {
			'user_agent': (
				"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
				"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
			),
			'viewport': {"width": 1280, "height": 2000},
		}
		if extra_context_kwargs:
			kwargs.update(extra_context_kwargs)
		context = browser_instance.browser.new_context(**kwargs)
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
def get_managed_browser_context_with_state(storage_state: dict | None = None):
	kwargs: Dict[str, Any] = {}
	if storage_state is not None:
		kwargs['storage_state'] = storage_state
	with get_managed_browser_context(kwargs) as context:
		yield context


@contextmanager
def get_managed_browser_page():
	page: Page | None = None
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
