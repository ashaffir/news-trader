import os
import requests
from typing import List, Dict, Any, Optional

try:
    # Local import guard to avoid circular imports during migrations/tests
    from core.models import ConfigControl  # type: ignore
except Exception:  # pragma: no cover
    ConfigControl = None  # type: ignore


def is_lan_model(model_name: str) -> bool:
    """Return True if model name looks like a local engine identifier.

    Heuristics:
    - Contains a slash (e.g., "qwen2.5:7b")
    - Starts with "lan:" prefix
    """
    if not model_name:
        return False
    return "/" in model_name or model_name.startswith("lan:")


def lan_chat_completion(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 512,
    base_url: Optional[str] = None,
) -> str:
    """Call a LAN LLM endpoint that follows an OpenAI-like chat.completions API and return content string.

    The endpoint is expected to accept JSON with fields: model, messages, temperature, max_tokens.
    """
    # Resolve base URL precedence: explicit arg > ConfigControl > env > default
    url = base_url
    if not url and ConfigControl:
        try:
            cc = ConfigControl.objects.filter(name="LAN_LLM_URL").first()
            if cc and cc.value:
                url = str(cc.value)
        except Exception:
            url = None
    if not url:
        url = os.getenv(
            "LAN_LLM_URL",
            "http://10.100.102.121:8080/api/generate",
        )

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Expect OpenAI-like response shape
    return data["choices"][0]["message"]["content"]


