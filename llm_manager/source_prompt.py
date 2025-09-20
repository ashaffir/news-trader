import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


LLM_SCHEMA_EXAMPLE = {
    "recommended_method": "web",
    "confidence_score": 0.85,
    "reasoning": [],
    "selectors": {},
    "api": {},
    "rss": {},
    "requires_javascript": False,
}


def _is_url_public_http(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        import ipaddress, socket
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                resolved = socket.gethostbyname(hostname)
                ip = ipaddress.ip_address(resolved)
            except Exception:
                return False
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
        return True
    except Exception:
        return False


def _fetch_page_sample(url: str, max_bytes: int = 150_000) -> Dict[str, Any]:
    rss_links: List[Dict[str, str]] = []
    content_preview = ""
    status_code = None

    try:
        if not _is_url_public_http(url):
            raise ValueError("URL is not a public HTTP/HTTPS address")
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NewsTrader/1.0)"
        })
        status_code = resp.status_code
        text = resp.text or ""
        content_preview = text[:max_bytes]
    except Exception as e:
        logger.warning(f"Failed to fetch page sample for {url}: {e}")

    try:
        from bs4 import BeautifulSoup
        if content_preview:
            soup = BeautifulSoup(content_preview, "html.parser")
            for link in soup.find_all("link", attrs={"type": ["application/rss+xml", "application/atom+xml"]}):
                href = link.get("href")
                title = link.get("title") or "RSS Feed"
                if href:
                    rss_links.append({"url": href, "title": title})
    except Exception:
        pass

    return {
        "status_code": status_code,
        "content_preview": content_preview,
        "rss_links": rss_links,
    }


def _build_llm_prompt(url: str, page_sample: Dict[str, Any]) -> List[Dict[str, str]]:
    system = (
        "You are a senior web data extraction engineer. Given a URL and an optional HTML preview, "
        "determine the most reliable way to extract a list of news posts. "
        "Prefer RSS or documented APIs when available; otherwise propose robust CSS selectors. "
        "Return ONLY a JSON object following this schema: "
        + json.dumps(LLM_SCHEMA_EXAMPLE, indent=2)
        + ". Do not include any text outside the JSON."
    )

    user = (
        f"URL: {url}\n\n"
        f"Page status: {page_sample.get('status_code')}\n"
        f"Discovered RSS links (may be relative): {page_sample.get('rss_links', [])}\n\n"
        "HTML preview (truncated):\n" + (page_sample.get("content_preview") or "")
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


__all__ = [
    "_is_url_public_http",
    "_fetch_page_sample",
    "_build_llm_prompt",
    "LLM_SCHEMA_EXAMPLE",
]


