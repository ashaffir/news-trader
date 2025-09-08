import os
from unittest.mock import patch
from django.test import TestCase


class TestLlmMetrics(TestCase):
    def test_lan_chat_completion_posts_metrics(self):
        from core.utils.llm import lan_chat_completion

        captured = {}

        class FakeResp:
            def __init__(self, status_code=200, data=None):
                self.status_code = status_code
                self._data = data or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError("http error")

            def json(self):
                return self._data

        def fake_post(url, json=None, headers=None, timeout=None):
            if url.endswith("/api/generate"):
                return FakeResp(
                    200,
                    {
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
                    },
                )
            if url.endswith("/track_inference"):
                captured["payload"] = dict(json or {})
                return FakeResp(200, {})
            raise AssertionError(f"Unexpected URL: {url}")

        with patch.dict(os.environ, {"LLM_ROOT_URL": "http://llm.root"}, clear=False):
            with patch("core.utils.llm.requests.post", side_effect=fake_post):
                content = lan_chat_completion(
                    model="lan:qwen2.5:7b",
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=0.0,
                    max_tokens=10,
                    base_url="http://llm.local/api/generate",
                )
                assert content == "ok"
                assert "payload" in captured
                assert captured["payload"]["prompt_tokens"] == 12
                assert captured["payload"]["generated_tokens"] == 34
                assert captured["payload"]["total_tokens"] == 46
                assert captured["payload"]["model"] == "lan:qwen2.5:7b"
                assert captured["payload"]["provider"] == "lan"

    def test_openai_posts_metrics_via_source_llm(self):
        from core.source_llm import analyze_news_source_with_llm

        captured = {}

        class FakeUsage:
            prompt_tokens = 21
            completion_tokens = 8
            total_tokens = 29

        class FakeMsg:
            content = "{\n  \"recommended_method\": \"web\",\n  \"confidence_score\": 0.7,\n  \"reasoning\": [],\n  \"selectors\": {}\n}"

        class FakeChoice:
            message = FakeMsg()

        class FakeResp:
            choices = [FakeChoice()]
            usage = FakeUsage()

        class FakeChat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return FakeResp()

        class FakeClient:
            chat = FakeChat()

        def fake_post(url, json=None, headers=None, timeout=None):
            if url.endswith("/track_inference"):
                captured["payload"] = dict(json or {})
                class _R:
                    status_code = 200
                    def raise_for_status(self):
                        return None
                return _R()
            raise AssertionError(f"Unexpected URL for metrics: {url}")

        with patch.dict(os.environ, {"LLM_ROOT_URL": "http://llm.root", "OPENAI_API_KEY": "x", "SOURCE_LLM_MODEL": "gpt-4o-mini"}, clear=False):
            with patch("core.source_llm._fetch_page_sample", return_value={"status_code": 200, "content_preview": "<html></html>", "rss_links": []}):
                with patch("openai.OpenAI", return_value=FakeClient()):
                    with patch("core.utils.llm.requests.post", side_effect=fake_post):
                        res = analyze_news_source_with_llm("https://example.com")
                        assert isinstance(res, dict)
                        assert "payload" in captured
                        assert captured["payload"].get("prompt_tokens") == 21
                        assert captured["payload"].get("generated_tokens") == 8
                        assert captured["payload"].get("total_tokens") == 29
                        assert captured["payload"].get("provider") == "openai"


