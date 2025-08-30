import re
import logging
from typing import List, Optional, Dict

from urllib.parse import urlparse

from core.browser_manager import get_managed_browser_page


logger = logging.getLogger(__name__)


URL_REGEX = re.compile(r"https?://[^\s)]+", re.IGNORECASE)


def find_urls_in_text(text: str) -> List[str]:
    """Extract absolute URLs from arbitrary text.

    - Returns URLs in their original order of appearance
    - De-duplicates while preserving order
    """
    if not text:
        return []
    found = URL_REGEX.findall(text)
    seen = set()
    ordered: List[str] = []
    for u in found:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def _is_probable_article_url(url: str) -> bool:
    """Heuristic: identify if URL likely points to a news article."""
    try:
        netloc = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()
        if not netloc:
            return False
        # Exclude social status links
        if any(s in netloc for s in ("twitter.com", "x.com", "t.co")) and "/status/" in path:
            return False
        # Include common article patterns
        article_markers = [
            "/news/",
            "/article/",
            "/stories/",
            "/story/",
            "/202",
        ]
        return any(m in path for m in article_markers)
    except Exception:
        return False


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract_article_text(url: str, timeout_ms: int = 15000, max_chars: int = 6000) -> Dict[str, Optional[str]]:
    """Open a URL with Playwright and return a best-effort article text excerpt.

    Returns dict with keys: { success: bool, url, title, text, error }
    """
    result: Dict[str, Optional[str] | bool] = {
        "success": False,
        "url": url,
        "title": None,
        "text": None,
        "error": None,
    }
    if not url:
        result["error"] = "empty_url"
        return result

    try:
        with get_managed_browser_page() as page:
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Title
            try:
                result["title"] = page.title()
            except Exception:
                result["title"] = None

            # Try a set of robust selectors, from most specific to generic
            main_selectors = [
                "article",
                "main article",
                "div[itemprop='articleBody']",
                "[data-testid*='article']",
                "[class*='article']",
                "section[role='main']",
                "main",
            ]

            content_text: Optional[str] = None
            main_el = None
            for sel in main_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        main_el = el
                        break
                except Exception:
                    continue

            if main_el:
                try:
                    # Prefer paragraph aggregation within main element
                    paragraphs = main_el.query_selector_all("p")
                    if paragraphs:
                        texts = []
                        for p in paragraphs:
                            try:
                                t = p.inner_text()
                                if t and len(_collapse_whitespace(t)) > 0:
                                    texts.append(_collapse_whitespace(t))
                            except Exception:
                                continue
                        content_text = "\n".join(texts)
                    else:
                        content_text = _collapse_whitespace(main_el.inner_text())
                except Exception:
                    content_text = None

            # Fallback: collect visible paragraphs across body
            if not content_text:
                try:
                    paragraphs = page.query_selector_all("p")
                    texts = []
                    for p in paragraphs[:120]:
                        try:
                            t = p.inner_text()
                            if t and len(_collapse_whitespace(t)) > 0:
                                texts.append(_collapse_whitespace(t))
                        except Exception:
                            continue
                    content_text = "\n".join(texts)
                except Exception:
                    content_text = None

            if content_text:
                # Trim to max_chars but try to end on sentence boundary
                if len(content_text) > max_chars:
                    trimmed = content_text[:max_chars]
                    last_period = trimmed.rfind(".")
                    if last_period > max_chars * 0.6:
                        trimmed = trimmed[: last_period + 1]
                    content_text = trimmed

                result["text"] = content_text
                result["success"] = True
            else:
                result["error"] = "no_text_found"

            return result

    except Exception as e:
        err = str(e)
        logger.debug(f"extract_article_text error for {url}: {err}")
        result["error"] = err
        return result


def pick_best_article_url(candidate_urls: List[str]) -> Optional[str]:
    """Pick the most likely article URL from a list of candidates."""
    if not candidate_urls:
        return None
    # Prefer non-social, article-like URLs
    for u in candidate_urls:
        if _is_probable_article_url(u):
            return u
    # Otherwise return first non-social URL
    for u in candidate_urls:
        try:
            netloc = urlparse(u).netloc.lower()
            if not any(s in netloc for s in ("twitter.com", "x.com", "t.co")):
                return u
        except Exception:
            continue
    # Fallback to first URL
    return candidate_urls[0]


