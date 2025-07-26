from django.test import TestCase
from unittest.mock import patch, MagicMock
import os
import json
import requests # Added this import

from .models import Source, Post, Analysis, Trade
from .tasks import analyze_post, _scrape_web, _fetch_api_posts, scrape_posts

class LLMAnalysisTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(name="Test Source", url="http://test.com")
        self.post = Post.objects.create(source=self.source, content="This is a test post about TSLA.", url="http://test.com/post/1")
        os.environ['OPENAI_API_KEY'] = 'test_api_key' # Mock API key

    @patch('openai.OpenAI')
    @patch('core.tasks.execute_trade.delay')
    def test_analyze_post_success(self, mock_execute_trade_delay, mock_openai):
        mock_chat_completion = MagicMock()
        mock_chat_completion.choices[0].message.content = json.dumps({
            "symbol": "TSLA",
            "direction": "buy",
            "confidence": 0.9,
            "reason": "Positive sentiment detected."
        })
        mock_openai.return_value.chat.completions.create.return_value = mock_chat_completion

        analyze_post(self.post.id)

        self.assertTrue(Analysis.objects.filter(post=self.post).exists())
        analysis = Analysis.objects.get(post=self.post)
        self.assertEqual(analysis.symbol, "TSLA")
        self.assertEqual(analysis.direction, "buy")
        self.assertEqual(analysis.confidence, 0.9)
        self.assertIn("Positive sentiment", analysis.reason)
        self.assertIsNotNone(analysis.raw_llm_response)
        mock_execute_trade_delay.assert_called_once_with(analysis.id)

    @patch('openai.OpenAI')
    @patch('core.tasks.execute_trade.delay')
    def test_analyze_post_invalid_json(self, mock_execute_trade_delay, mock_openai):
        mock_chat_completion = MagicMock()
        mock_chat_completion.choices[0].message.content = "invalid json"
        mock_openai.return_value.chat.completions.create.return_value = mock_chat_completion

        analyze_post(self.post.id)

        self.assertTrue(Analysis.objects.filter(post=self.post).exists())
        analysis = Analysis.objects.get(post=self.post)
        self.assertEqual(analysis.symbol, "ERROR")
        self.assertEqual(analysis.direction, "hold")
        self.assertIn("LLM returned invalid JSON", analysis.reason)
        self.assertIsNotNone(analysis.raw_llm_response)
        mock_execute_trade_delay.assert_not_called()

    @patch('openai.OpenAI')
    @patch('core.tasks.execute_trade.delay')
    def test_analyze_post_api_key_missing(self, mock_execute_trade_delay, mock_openai):
        del os.environ['OPENAI_API_KEY']
        analyze_post(self.post.id)
        self.assertFalse(Analysis.objects.filter(post=self.post).exists())
        mock_execute_trade_delay.assert_not_called()

class ScrapingTests(TestCase):
    def setUp(self):
        self.source_web = Source.objects.create(name="Test Web Source", url="http://example.com", scraping_method='web')
        self.source_api = Source.objects.create(name="Test API Source", url="http://api.example.com", scraping_method='api', api_endpoint="http://api.example.com/data", api_key_field="TEST_API_KEY", request_type="GET", request_params={'param': 'value'})
        self.source_both = Source.objects.create(name="Test Both Source", url="http://both.com", scraping_method='both', api_endpoint="http://api.both.com/data", api_key_field="TEST_API_KEY", request_type="GET", request_params={'param': 'value'})
        os.environ['TEST_API_KEY'] = 'mock_api_key'

    @patch('requests.get')
    @patch('core.tasks.analyze_post.delay')
    def test_scrape_web_success(self, mock_analyze_post_delay, mock_requests_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><p>Web scraped content.</p></body></html>"
        mock_requests_get.return_value = mock_response

        _scrape_web(self.source_web)

        mock_requests_get.assert_called_once_with(self.source_web.url)
        self.assertTrue(Post.objects.filter(source=self.source_web).exists())
        post = Post.objects.get(source=self.source_web)
        self.assertIn("Web scraped content", post.content)
        mock_analyze_post_delay.assert_called_once_with(post.id)

    @patch('requests.get', side_effect=requests.exceptions.RequestException("Network error"))
    @patch('core.tasks._create_simulated_post')
    def test_scrape_web_failure(self, mock_create_simulated_post, mock_requests_get):
        _scrape_web(self.source_web)
        mock_requests_get.assert_called_once_with(self.source_web.url)
        mock_create_simulated_post.assert_called_once()

    @patch('requests.get')
    @patch('core.tasks.analyze_post.delay')
    def test_fetch_api_posts_get_success(self, mock_analyze_post_delay, mock_requests_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{'title': 'API Post 1', 'body': 'Content 1'}]
        mock_requests_get.return_value = mock_response

        _fetch_api_posts(self.source_api)

        mock_requests_get.assert_called_once_with(
            self.source_api.api_endpoint,
            headers={'Authorization': f'Bearer {os.getenv("TEST_API_KEY")}'},
            params={'param': 'value'}
        )
        self.assertTrue(Post.objects.filter(source=self.source_api).exists())
        post = Post.objects.get(source=self.source_api)
        self.assertIn("API Post 1", post.content)
        mock_analyze_post_delay.assert_called_once_with(post.id)

    @patch('requests.post')
    @patch('core.tasks.analyze_post.delay')
    def test_fetch_api_posts_post_success(self, mock_analyze_post_delay, mock_requests_post):
        self.source_api.request_type = 'POST'
        self.source_api.request_params = {'data_key': 'data_value'}
        self.source_api.save()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success', 'id': 123}
        mock_requests_post.return_value = mock_response

        _fetch_api_posts(self.source_api)

        mock_requests_post.assert_called_once()
        args, kwargs = mock_requests_post.call_args
        self.assertEqual(args[0], self.source_api.api_endpoint)
        self.assertIn('Authorization', kwargs['headers'])
        self.assertIn('Content-Type', kwargs['headers'])
        self.assertEqual(kwargs['data'], json.dumps({'data_key': 'data_value'}))

        self.assertTrue(Post.objects.filter(source=self.source_api).exists())
        post = Post.objects.get(source=self.source_api)
        self.assertIn("status", post.content)
        mock_analyze_post_delay.assert_called_once_with(post.id)

    @patch('requests.get', side_effect=requests.exceptions.RequestException("API network error"))
    @patch('core.tasks._create_simulated_post')
    def test_fetch_api_posts_failure(self, mock_create_simulated_post, mock_requests_get):
        _fetch_api_posts(self.source_api)
        mock_requests_get.assert_called_once()
        mock_create_simulated_post.assert_called_once()

    @patch('core.tasks._scrape_web')
    @patch('core.tasks._fetch_api_posts')
    def test_scrape_posts_web_method(self, mock_fetch_api_posts, mock_scrape_web):
        scrape_posts(source_id=self.source_web.id)
        mock_scrape_web.assert_called_once_with(self.source_web)
        mock_fetch_api_posts.assert_not_called()

    @patch('core.tasks._scrape_web')
    @patch('core.tasks._fetch_api_posts')
    def test_scrape_posts_api_method(self, mock_fetch_api_posts, mock_scrape_web):
        scrape_posts(source_id=self.source_api.id)
        mock_fetch_api_posts.assert_called_once_with(self.source_api)
        mock_scrape_web.assert_not_called()

    @patch('core.tasks._scrape_web')
    @patch('core.tasks._fetch_api_posts')
    def test_scrape_posts_both_method(self, mock_fetch_api_posts, mock_scrape_web):
        scrape_posts(source_id=self.source_both.id)
        mock_scrape_web.assert_called_once_with(self.source_both)
        mock_fetch_api_posts.assert_called_once_with(self.source_both)

    @patch('core.tasks._scrape_web')
    @patch('core.tasks._fetch_api_posts')
    def test_scrape_posts_all_sources(self, mock_fetch_api_posts, mock_scrape_web):
        scrape_posts()
        self.assertEqual(mock_scrape_web.call_count, 2) # source_web and source_both
        self.assertEqual(mock_fetch_api_posts.call_count, 2) # source_api and source_both
