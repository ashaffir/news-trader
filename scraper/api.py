import logging

from core.tasks import _scrape_api_source as _core_scrape_api

logger = logging.getLogger(__name__)


def scrape_api_source(source) -> None:
	_core_scrape_api(source)
