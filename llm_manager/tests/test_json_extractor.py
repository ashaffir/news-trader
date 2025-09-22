import json

from llm_manager.utils import extract_json_from_response
from core.utils.llm import lan_chat_completion
from llm_manager.post_prompt import analysis_json_schema


def test_extract_returns_valid_json_as_is():
    content = '{"a": 1, "b": "x"}'
    out = extract_json_from_response(content)
    assert json.loads(out) == {"a": 1, "b": "x"}


def test_extract_handles_markdown_fence_json():
    content = """
    Here is the result:
    ```json
    {"a": 2, "b": "y"}
    ```
    """
    out = extract_json_from_response(content)
    assert json.loads(out) == {"a": 2, "b": "y"}


def test_extract_strips_thinking_and_prefaces():
    content = "Thinking... We need to respond with JSON. {\n  \"a\": 3, \n  \"b\": \"z\"\n}"
    out = extract_json_from_response(content)
    assert json.loads(out) == {"a": 3, "b": "z"}


def test_extract_trims_leading_text_before_brace():
    content = "Note: below is JSON -> {\"a\": 4} trailing"
    out = extract_json_from_response(content)
    assert json.loads(out) == {"a": 4}


def test_extract_fallback_between_first_and_last_brace():
    content = "prefix {\"a\": 5, \"nested\": {\"c\": 7}} suffix"
    out = extract_json_from_response(content)
    assert json.loads(out) == {"a": 5, "nested": {"c": 7}}


def test_chat_endpoint_payload_build(monkeypatch):
    posted = {}

    class FakeResp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data or {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("err")
        def json(self):
            return self._data

    def fake_post(url, json=None, headers=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        if url.endswith("/api/chat"):
            return FakeResp(200, {"message": {"content": "{\\n  \\\"symbol\\\": \\\"N/A\\\"\\n}"}})
        raise AssertionError("Unexpected URL: " + url)

    monkeypatch.setenv("LAN_LLM_URL", "http://lan.local")
    monkeypatch.setattr("core.utils.llm.requests.post", fake_post)

    content = lan_chat_completion(
        model="llama3",
        messages=[{"role": "user", "content": "text"}],
        use_chat_endpoint=True,
        json_schema=analysis_json_schema(),
    )
    assert posted["url"].endswith("/api/chat")
    assert posted["json"].get("format") == analysis_json_schema()
    assert content.strip().startswith("{")
