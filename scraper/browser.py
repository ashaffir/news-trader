import logging

from core.tasks import _scrape_with_browser as _core_scrape_browser

logger = logging.getLogger(__name__)


def scrape_with_browser(source) -> None:
	_core_scrape_browser(source)
