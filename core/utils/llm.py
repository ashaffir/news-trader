import os
import time
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
    - Contains a slash (e.g., "llama/7b")
    - Contains a colon (e.g., "qwen2.5:7b")
    - Starts with "lan:" prefix
    """
    if not model_name:
        return False
    return "/" in model_name or ":" in model_name or model_name.startswith("lan:")


def _resolve_llm_root_url() -> Optional[str]:
    """Resolve the LLM root URL for metrics tracking.

    Precedence: ConfigControl("LLM_ROOT_URL") > env LLM_ROOT_URL > None
    """
    # ConfigControl takes precedence if available
    if ConfigControl:
        try:
            cc = ConfigControl.objects.filter(name="LLM_ROOT_URL").first()
            if cc and cc.value:
                return str(cc.value).rstrip("/")
        except Exception:
            pass
    env_url = os.getenv("LLM_ROOT_URL")
    return env_url.rstrip("/") if env_url else None


def post_llm_metrics(
    prompt_tokens: Optional[int] = None,
    generated_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    latency_ms: Optional[float] = None,
) -> None:
    """Best-effort POST of LLM usage metrics to <LLM ROOT URL>/track_inference.

    Swallows all exceptions to avoid impacting main execution.
    """
    try:
        root = _resolve_llm_root_url()
        if not root:
            return
        url = f"{root}/track_inference"
        payload: Dict[str, Any] = {}
        if prompt_tokens is not None:
            payload["prompt_tokens"] = int(prompt_tokens)
        if generated_tokens is not None:
            payload["generated_tokens"] = int(generated_tokens)
        if total_tokens is not None:
            payload["total_tokens"] = int(total_tokens)
        if model:
            payload["model"] = model
        if provider:
            payload["provider"] = provider
        if latency_ms is not None:
            payload["latency_ms"] = float(latency_ms)
        if not payload:
            return
        requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except Exception:
        # Do not raise - metrics are best-effort only
        pass


def lan_chat_completion(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 512,
    base_url: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
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

    # Decide endpoint style: OpenAI-like chat.completions vs generate-style
    is_generate_endpoint = str(url).endswith("/api/generate") or "/generate" in str(url)

    if is_generate_endpoint:
        # Combine messages into a single prompt string
        def _combine_messages(msgs: List[Dict[str, str]]) -> str:
            parts: List[str] = []
            for m in msgs:
                role = (m.get("role") or "").lower()
                content = m.get("content") or ""
                prefix = "System:" if role == "system" else ("User:" if role == "user" else ("Assistant:" if role == "assistant" else f"{role.title()}:"))
                parts.append(f"{prefix} {content}")
            return "\n\n".join(parts)

        prompt_text = _combine_messages(messages)
        # If caller asked for json_object, reinforce instruction for strict JSON
        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            prompt_text += "\n\nReturn only a valid JSON object with no extra text."

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt_text,
            "stream": False,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
    else:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if response_format is not None:
            payload["response_format"] = response_format

    start_time = time.monotonic()
    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)
    resp.raise_for_status()
    elapsed_ms = (time.monotonic() - start_time) * 1000.0
    data = resp.json()
    # Support both OpenAI-like and generate-style JSON
    content: str
    if isinstance(data, dict) and "choices" in data:
        content = data["choices"][0]["message"]["content"]
    elif isinstance(data, dict) and "response" in data:
        content = data["response"]
    else:
        # Fallback: attempt common alternate shapes
        content = (
            data.get("content")
            if isinstance(data, dict)
            else str(data)
        )

    # Post usage metrics if provided by the server (both styles)
    try:
        usage: Dict[str, Any] = data.get("usage", {}) if isinstance(data, dict) else {}
        prompt_tokens = usage.get("prompt_tokens")
        generated_tokens = usage.get("completion_tokens", usage.get("generated_tokens"))
        total_tokens = usage.get("total_tokens")

        # Map generate-style fields if present
        if prompt_tokens is None and isinstance(data, dict):
            if isinstance(data.get("prompt_eval_count"), int):
                prompt_tokens = data.get("prompt_eval_count")
        if generated_tokens is None and isinstance(data, dict):
            if isinstance(data.get("eval_count"), int):
                generated_tokens = data.get("eval_count")
        if total_tokens is None and isinstance(data, dict):
            pe = data.get("prompt_eval_count")
            ec = data.get("eval_count")
            if isinstance(pe, int) or isinstance(ec, int):
                total_tokens = (pe or 0) + (ec or 0)

        # Prefer server-reported total_duration (ns) if available
        reported_latency_ms: Optional[float] = None
        if isinstance(data, dict) and isinstance(data.get("total_duration"), int):
            # Convert nanoseconds to milliseconds
            reported_latency_ms = float(data.get("total_duration")) / 1_000_000.0

        post_llm_metrics(
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            generated_tokens=generated_tokens if isinstance(generated_tokens, int) else None,
            total_tokens=total_tokens if isinstance(total_tokens, int) else None,
            model=model,
            provider="lan",
            latency_ms=reported_latency_ms if reported_latency_ms is not None else elapsed_ms,
        )
    except Exception:
        pass

    return content


