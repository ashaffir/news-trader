import logging

from core.tasks import _scrape_rss_feed as _core_scrape_rss

logger = logging.getLogger(__name__)


def scrape_rss_feed(source) -> None:
	_core_scrape_rss(source)
