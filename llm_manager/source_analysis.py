import os
import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
import openai

from llm_manager.utils import post_llm_metrics, extract_json_from_response
from llm_manager.source_prompt import (
    _is_url_public_http,
    _fetch_page_sample,
    _build_llm_prompt,
)

logger = logging.getLogger(__name__)


def analyze_news_source_with_llm(url: str) -> Dict[str, Any]:
    """Analyze a news source via LLM and return a normalized analysis dict."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    page_sample = _fetch_page_sample(url)
    messages = _build_llm_prompt(url, page_sample)

    client = openai.OpenAI(api_key=api_key)
    try:
        start_time = __import__("time").monotonic()
        resp = client.chat.completions.create(
            model=os.getenv("SOURCE_LLM_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")),
            messages=messages,
            response_format={"type": "json_object"},
            temperature=float(os.getenv("SOURCE_LLM_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("SOURCE_LLM_MAX_TOKENS", "1200")),
        )
        content = resp.choices[0].message.content
        # Clean potential extra commentary around JSON
        content = extract_json_from_response(content or "")
        try:
            elapsed_ms = (__import__("time").monotonic() - start_time) * 1000.0
            usage = getattr(resp, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            post_llm_metrics(
                prompt_tokens=prompt_tokens,
                generated_tokens=completion_tokens,
                total_tokens=total_tokens,
                model=os.getenv("SOURCE_LLM_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")),
                provider="openai",
                latency_ms=elapsed_ms,
            )
        except Exception:
            pass
        parsed = json.loads(content)
    except Exception as e:
        logger.error(f"LLM analysis failed for {url}: {e}")
        raise

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

    rss_feeds: List[Dict[str, str]] = []
    api_endpoints: List[Dict[str, Any]] = []

    rss = parsed.get("rss")
    if isinstance(rss, dict) and rss.get("feed_url") and _is_valid_rss(rss["feed_url"]):
        rss_feeds.append({"url": rss["feed_url"], "title": "RSS Feed"})
    else:
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
        source_kwargs["scraping_method"] = "web"

    api = llm_raw.get("api")
    if isinstance(api, dict) and api.get("endpoint"):
        source_kwargs["api_endpoint"] = api.get("endpoint")
        source_kwargs["request_type"] = api.get("method", "GET").upper()

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
        for key in [
            "response_path", "content_field", "url_field",
            "score_field", "min_score", "params", "headers",
        ]:
            if key in api:
                data_extraction_config[key] = api[key]

    if data_extraction_config:
        source_kwargs["data_extraction_config"] = data_extraction_config

    return source_kwargs


__all__ = [
    "analyze_news_source_with_llm",
    "build_source_kwargs_from_llm_analysis",
]


