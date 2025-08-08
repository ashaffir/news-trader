import os
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
import openai

logger = logging.getLogger(__name__)


LLM_SCHEMA_EXAMPLE = {
    "recommended_method": "web",  # one of: web | api | rss | both
    "confidence_score": 0.85,      # 0..1
    "reasoning": [
        "RSS not detected; clear article containers found",
        "API endpoints not obvious"
    ],
    # For web scraping
    "selectors": {
        "container": ".news-card",
        "title": ["h3", ".title"],
        "content": ["p", ".summary"],
        "link": "a"
    },
    # For API scraping (optional)
    "api": {
        "endpoint": "https://example.com/api/news",
        "method": "GET",
        "headers": {"User-Agent": "NewsTrader/1.0"},
        "params": {"limit": 20},
        "response_path": "articles",
        "content_field": "title",
        "url_field": "url",
        "score_field": "score",
        "min_score": 0
    },
    # For RSS (optional)
    "rss": {
        "feed_url": "https://<same-domain-rss-feed-url>"
    },
    # Optional hints
    "requires_javascript": False
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
            # Resolve DNS to IP and check
            try:
                resolved = socket.gethostbyname(hostname)
                ip = ipaddress.ip_address(resolved)
            except Exception:
                return False
        # Disallow private, loopback, link-local
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
        return True
    except Exception:
        return False


def _fetch_page_sample(url: str, max_bytes: int = 150_000) -> Dict[str, Any]:
    """Fetch a lightweight sample of the target page to guide the LLM.

    Returns a dict containing status_code, content_preview, and discovered RSS links.
    """
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

    # Lightweight RSS discovery in the preview
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
    """Construct a system+user prompt that forces a strict JSON schema output."""
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


def analyze_news_source_with_llm(url: str) -> Dict[str, Any]:
    """Analyze a news source via LLM and return a normalized analysis dict.

    The result mirrors the structure used by the UI: includes a top-level
    recommended_config and lightweight fields for compatibility.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    page_sample = _fetch_page_sample(url)
    messages = _build_llm_prompt(url, page_sample)

    # Use the same OpenAI client pattern used elsewhere for consistency
    client = openai.OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=os.getenv("SOURCE_LLM_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")),
            messages=messages,
            response_format={"type": "json_object"},
            temperature=float(os.getenv("SOURCE_LLM_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("SOURCE_LLM_MAX_TOKENS", "1200")),
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)
    except Exception as e:
        logger.error(f"LLM analysis failed for {url}: {e}")
        raise

    # Normalize into the UI-compatible shape
    domain = urlparse(url).netloc

    def _is_same_domain(u: str) -> bool:
        try:
            return urlparse(u).netloc.endswith(domain)
        except Exception:
            return False

    def _is_valid_rss(u: str) -> bool:
        try:
            if not _is_url_public_http(u):
                return False
            # same-domain or typical feeds subdomain
            parsed_u = urlparse(u)
            if not parsed_u.scheme or not parsed_u.netloc:
                return False
            if not (_is_same_domain(u) or parsed_u.netloc.startswith("feeds.")):
                return False
            h = requests.head(u, timeout=6)
            if h.status_code == 200:
                ctype = h.headers.get("content-type", "").lower()
                if "xml" in ctype or "rss" in ctype or "atom" in ctype:
                    return True
            g = requests.get(u, timeout=6)
            if g.status_code != 200:
                return False
            text = (g.text or "")[:400].lower()
            return "<rss" in text or "<feed" in text
        except Exception:
            return False
    recommended_config: Dict[str, Any] = {
        "recommended_method": parsed.get("recommended_method", "web"),
        "scraping_method": parsed.get("recommended_method", "web"),
        "selectors": parsed.get("selectors") or {},
        "alternative_methods": [],
        "confidence_score": float(parsed.get("confidence_score", 0.0)),
        "reasoning": parsed.get("reasoning", []),
    }

    if parsed.get("requires_javascript") is True:
        recommended_config["requires_javascript"] = True

    # Expose rss/api findings in a compatible way for the template
    rss_feeds: List[Dict[str, str]] = []
    api_endpoints: List[Dict[str, Any]] = []

    rss = parsed.get("rss")
    if isinstance(rss, dict) and rss.get("feed_url") and _is_valid_rss(rss["feed_url"]):
        rss_feeds.append({"url": rss["feed_url"], "title": "RSS Feed"})
    else:
        # If LLM said RSS but validation failed, ensure we don't force RSS
        if recommended_config["recommended_method"] == "rss":
            recommended_config["recommended_method"] = "web"
            recommended_config["scraping_method"] = "web"

    api = parsed.get("api")
    if isinstance(api, dict) and api.get("endpoint"):
        api_endpoints.append({
            "url": api.get("endpoint"),
            "type": "llm_suggested",
            "method": api.get("method", "GET"),
        })

    analysis: Dict[str, Any] = {
        "url": url,
        "domain": domain,
        "rss_feeds": rss_feeds,
        "api_endpoints": api_endpoints,
        "page_analysis": {
            "requires_javascript": bool(parsed.get("requires_javascript", False)),
            "framework_detected": None,
            "total_links": 0,
            "article_links": 0,
            "meta_info": {},
        },
        "article_patterns": {"common_patterns": []},
        "recommended_config": recommended_config,
        "analyzed_at": __import__("datetime").datetime.now().isoformat(),
    }

    # Attach raw details for downstream mapping when creating Source
    analysis["llm_raw"] = parsed
    return analysis


def build_source_kwargs_from_llm_analysis(url: str, name: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Transform the LLM analysis into kwargs for creating a `Source` object."""
    config = analysis.get("recommended_config", {})
    llm_raw = analysis.get("llm_raw", {})
    method = (config.get("recommended_method") or "web").lower()

    source_kwargs: Dict[str, Any] = {
        "name": name,
        "url": url,
        "description": f"LLM auto-configured source. Confidence: {config.get('confidence_score', 0):.2f}",
    }

    if method == "both":
        source_kwargs["scraping_method"] = "both"
    elif method == "api":
        source_kwargs["scraping_method"] = "api"
    else:
        # For rss/web, keep web as primary (rss captured in data_extraction_config)
        source_kwargs["scraping_method"] = "web"

    # If API suggested, map fields
    api = llm_raw.get("api")
    if isinstance(api, dict) and api.get("endpoint"):
        source_kwargs["api_endpoint"] = api.get("endpoint")
        source_kwargs["request_type"] = api.get("method", "GET").upper()

    # Build data_extraction_config
    data_extraction_config: Dict[str, Any] = {
        "auto_generated": True,
        "confidence_score": config.get("confidence_score", 0.0),
        "analysis_source": "llm",
    }

    selectors = llm_raw.get("selectors") or config.get("selectors")
    if selectors:
        data_extraction_config["selectors"] = selectors

    rss = llm_raw.get("rss")
    if isinstance(rss, dict) and rss.get("feed_url"):
        # Validate RSS before enabling to avoid bad overrides
        try:
            valid = False
            feed_url = rss.get("feed_url")
            from urllib.parse import urlparse as _p
            if feed_url and _p(feed_url).scheme:
                h = requests.head(feed_url, timeout=6)
                if h.status_code == 200 and any(k in h.headers.get("content-type", "").lower() for k in ("xml", "rss", "atom")):
                    valid = True
            if valid:
                data_extraction_config.update({
                    "rss_feed": True,
                    "feed_url": feed_url,
                })
        except Exception:
            pass

    if isinstance(api, dict) and api.get("endpoint"):
        # Map API response extraction details if provided
        for key in [
            "response_path", "content_field", "url_field",
            "score_field", "min_score", "params", "headers",
        ]:
            if key in api:
                data_extraction_config[key] = api[key]

    if data_extraction_config:
        source_kwargs["data_extraction_config"] = data_extraction_config

    return source_kwargs


