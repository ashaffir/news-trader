import json

from llm_manager.utils import extract_json_from_response


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


