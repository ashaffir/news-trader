"""Shim module re-exporting from llm_manager.utils for backward compatibility."""
import requests as requests  # exposed for test monkeypatch compatibility
from llm_manager.utils import (  # noqa: F401
    is_lan_model,
    post_llm_metrics,
    lan_chat_completion,
)

