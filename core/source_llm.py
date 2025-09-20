"""Shim module re-exporting functions from llm_manager for backward compatibility."""
from llm_manager.source_prompt import (  # noqa: F401
    _fetch_page_sample,
)
from llm_manager.source_analysis import (  # noqa: F401
    analyze_news_source_with_llm,
    build_source_kwargs_from_llm_analysis,
)

