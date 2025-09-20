import logging
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass
from queue import Queue, Empty
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, Browser

logger = logging.getLogger(__name__)


@dataclass
class BrowserInstance:
	browser: Browser
	playwright: Any
	created_at: datetime
	last_used: datetime
	usage_count: int = 0
	
	def is_expired(self, max_age_minutes: int = 30, max_usage: int = 100) -> bool:
		age_expired = datetime.now() - self.created_at > timedelta(minutes=max_age_minutes)
		usage_expired = self.usage_count >= max_usage
		return age_expired or usage_expired


class ThreadLocalBrowserPool:
	def __init__(self, max_browsers_per_thread: int = 2, max_browser_age_minutes: int = 30, max_browser_usage: int = 50):
		self.max_browsers_per_thread = max_browsers_per_thread
		self.max_browser_age_minutes = max_browser_age_minutes
		self.max_browser_usage = max_browser_usage
		self._thread_local = threading.local()
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
		logger.info(
			f"Initialized ThreadLocalBrowserPool: max_per_thread={max_browsers_per_thread}, max_age={max_browser_age_minutes}min, max_usage={max_browser_usage}"
		)
	
	def _get_thread_pool(self):
		if not hasattr(self._thread_local, 'pool'):
			self._thread_local.pool = Queue(maxsize=self.max_browsers_per_thread)
			self._thread_local.active_browsers = {}
			self._thread_local.thread_id = threading.get_ident()
			self._thread_local.shutdown = False
			logger.debug(f"Initialized thread-local browser pool for thread {self._thread_local.thread_id}")
		return self._thread_local
	
	def _create_browser_instance(self) -> BrowserInstance:
		thread_pool = self._get_thread_pool()
		thread_id = thread_pool.thread_id
		try:
			logger.info(f"Creating new Playwright browser instance for thread {thread_id}")
			playwright = sync_playwright().start()
			browser = playwright.chromium.launch(headless=True, args=self._browser_args)
			instance = BrowserInstance(browser=browser, playwright=playwright, created_at=datetime.now(), last_used=datetime.now())
			instance_id = id(instance)
			thread_pool.active_browsers[instance_id] = instance
			logger.info(f"Created browser instance {instance_id} for thread {thread_id}")
			return instance
		except Exception as e:
			logger.error(f"Failed to create browser instance for thread {thread_id}: {e}")
			raise
	
	def _cleanup_browser_instance(self, instance: BrowserInstance):
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
		thread_pool = self._get_thread_pool()
		if thread_pool.shutdown:
			return
		expired_instances = []
		for _, instance in list(thread_pool.active_browsers.items()):
			if instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
				expired_instances.append(instance)
		for instance in expired_instances:
			logger.info(
				f"Retiring expired browser instance {id(instance)} (age: {datetime.now() - instance.created_at}, usage: {instance.usage_count})"
			)
			self._cleanup_browser_instance(instance)
	
	def get_browser(self) -> BrowserInstance:
		thread_pool = self._get_thread_pool()
		if thread_pool.shutdown:
			raise RuntimeError(f"Browser pool for thread {thread_pool.thread_id} is shutdown")
		self._cleanup_expired_browsers()
		try:
			instance = thread_pool.pool.get_nowait()
			if not instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
				instance.last_used = datetime.now()
				instance.usage_count += 1
				return instance
			else:
				self._cleanup_browser_instance(instance)
		except Empty:
			if len(thread_pool.active_browsers) >= self.max_browsers_per_thread:
				import time
				logger.warning(
					f"Thread {thread_pool.thread_id} browser pool at capacity ({self.max_browsers_per_thread}), waiting for available browser"
				)
				time.sleep(0.1)
				try:
					instance = thread_pool.pool.get(timeout=5.0)
					instance.last_used = datetime.now()
					instance.usage_count += 1
					return instance
				except Empty:
					raise RuntimeError(f"No browser available in thread {thread_pool.thread_id} within 5s timeout")
		return self._create_browser_instance()
	
	def return_browser(self, instance: BrowserInstance):
		thread_pool = self._get_thread_pool()
		if thread_pool.shutdown:
			self._cleanup_browser_instance(instance)
			return
		if instance.is_expired(self.max_browser_age_minutes, self.max_browser_usage):
			self._cleanup_browser_instance(instance)
			return
		thread_pool.pool.put_nowait(instance)
	
	def get_pool_stats(self) -> Dict[str, Any]:
		try:
			thread_pool = self._get_thread_pool()
			active_count = len(thread_pool.active_browsers)
			pool_size = thread_pool.pool.qsize()
			return {
				"thread_id": thread_pool.thread_id,
				"active_browsers": active_count,
				"available_in_pool": pool_size,
				"max_browsers_per_thread": self.max_browsers_per_thread,
				"in_use": active_count - pool_size,
				"pool_utilization": f"{(active_count / self.max_browsers_per_thread) * 100:.1f}%" if self.max_browsers_per_thread > 0 else "0%",
			}
		except Exception as e:
			return {"error": str(e), "thread_id": threading.get_ident()}
	
	def shutdown(self):
		try:
			thread_pool = self._get_thread_pool()
			thread_pool.shutdown = True
			for instance in list(thread_pool.active_browsers.values()):
				self._cleanup_browser_instance(instance)
			while not thread_pool.pool.empty():
				try:
					thread_pool.pool.get_nowait()
				except Empty:
					break
		except Exception as e:
			logger.warning(f"Error during thread {threading.get_ident()} browser pool shutdown: {e}")


_browser_pool: Optional[ThreadLocalBrowserPool] = None
_pool_lock = threading.Lock()


def get_browser_pool() -> ThreadLocalBrowserPool:
	global _browser_pool
	if _browser_pool is None:
		with _pool_lock:
			if _browser_pool is None:
				_browser_pool = ThreadLocalBrowserPool()
	return _browser_pool
