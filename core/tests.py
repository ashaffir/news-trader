from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock
from unittest import skipIf
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token
from core.models import Source, Post, Analysis, Trade, TradingConfig, ApiResponse, AlertSettings
from core.tasks import analyze_post, execute_trade, scrape_posts
from unittest.mock import patch, MagicMock
from core.source_llm import analyze_news_source_with_llm, build_source_kwargs_from_llm_analysis
import json
import os
import asyncio
import time
from datetime import datetime


class ModelTests(TestCase):
    """Test core models functionality."""

    def setUp(self):
        self.trading_config = TradingConfig.objects.create(
            name="Test Config",
            is_active=True,
            default_position_size=100.0,
            stop_loss_percentage=5.0,
            take_profit_percentage=10.0,
            min_confidence_threshold=0.7,
        )

        self.source = Source.objects.create(
            name="Test Source",
            url="https://example.com",
            scraping_method="web",
            scraping_enabled=True,
        )

        self.post = Post.objects.create(
            source=self.source,
            content="Tesla stock is expected to rise significantly",
            url="https://example.com/post/1",
        )

    def test_trading_config_creation(self):
        """Test TradingConfig model creation and properties."""
        config = self.trading_config
        self.assertEqual(config.name, "Test Config")
        self.assertTrue(config.is_active)
        self.assertEqual(config.default_position_size, 100.0)
        self.assertEqual(str(config), "Test Config (Active)")

    def test_source_model(self):
        """Test Source model creation and relationships."""
        source = self.source
        self.assertEqual(source.name, "Test Source")
        self.assertEqual(source.scraping_method, "web")
        self.assertTrue(source.scraping_enabled)
        self.assertEqual(source.scraping_status, "idle")

    def test_post_model(self):
        """Test Post model creation and relationships."""
        post = self.post
        self.assertEqual(post.source, self.source)
        self.assertIn("Tesla", post.content)
        self.assertEqual(
            str(post), f"Post from {self.source.name} at {post.created_at}"
        )

    def test_analysis_model(self):
        """Test Analysis model creation and relationships."""
        analysis = Analysis.objects.create(
            post=self.post,
            symbol="TSLA",
            direction="buy",
            confidence=0.85,
            reason="Positive sentiment about Tesla stock",
            trading_config_used=self.trading_config,
        )

        self.assertEqual(analysis.post, self.post)
        self.assertEqual(analysis.symbol, "TSLA")
        self.assertEqual(analysis.direction, "buy")
        self.assertEqual(analysis.confidence, 0.85)
        self.assertEqual(analysis.trading_config_used, self.trading_config)

    def test_trade_model_properties(self):
        """Test Trade model properties and calculations."""
        analysis = Analysis.objects.create(
            post=self.post,
            symbol="TSLA",
            direction="buy",
            confidence=0.85,
            reason="Test analysis",
        )

        trade = Trade.objects.create(
            analysis=analysis,
            symbol="TSLA",
            direction="buy",
            quantity=10,
            entry_price=100.0,
            exit_price=110.0,
            status="closed",
            realized_pnl=100.0,
            opened_at=timezone.now(),
            closed_at=timezone.now(),
            take_profit_price_percentage=10.0,
            stop_loss_price_percentage=2.0,
        )

        self.assertEqual(
            trade.current_pnl, 100.0
        )  # Should return realized_pnl when closed
        self.assertEqual(trade.symbol, "TSLA")
        self.assertEqual(trade.status, "closed")


class TaskTests(TestCase):
    """Test Celery tasks functionality."""

    def setUp(self):
        self.trading_config = TradingConfig.objects.create(
            name="Test Config", is_active=True, min_confidence_threshold=0.7, bot_enabled=True
        )

        self.source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

        self.post = Post.objects.create(
            source=self.source,
            content="Apple stock shows strong growth potential",
            url="https://example.com/post/1",
        )

    def test_simulated_post_validation(self):
        """Test that simulated posts are properly skipped during analysis."""
        from core.tasks import _is_simulated_post, analyze_post
        
        # Create a simulated post
        simulated_post = Post.objects.create(
            source=self.source,
            content="Simulated post from Test Source via api due to error: API config missing",
            url="simulated://Test_Source/api/abc123/def456",
        )
        
        # Create a real post for comparison
        real_post = Post.objects.create(
            source=self.source,
            content="Real news content about AAPL stock performance",
            url="https://example.com/real-news/123",
        )
        
        # Test validation function
        self.assertTrue(_is_simulated_post(simulated_post))
        self.assertFalse(_is_simulated_post(real_post))
        
        # Test that simulated post analysis is skipped
        with patch('core.tasks.logger') as mock_logger:
            analyze_post.apply(args=[simulated_post.id, True])
            # Allow any info call that includes the expected phrase, since other info logs may occur before/after
            info_calls = [str(call) for call in mock_logger.info.call_args_list]
            self.assertTrue(any('Skipping LLM analysis for simulated post' in c for c in info_calls))
        
        # Verify no Analysis object was created for simulated post
        self.assertFalse(Analysis.objects.filter(post=simulated_post).exists())

    @patch("core.tasks.openai.OpenAI")
    @patch("core.tasks.os.getenv")
    def test_analyze_post_task(self, mock_getenv, mock_openai):
        """Test the analyze_post Celery task."""

        # Mock environment variable and OpenAI response
        def mock_getenv_side_effect(key, default=None):
            if key == "OPENAI_API_KEY":
                return "fake-api-key"
            elif key == "ALPACA_API_KEY":
                return "fake-alpaca-key"
            elif key == "ALPACA_SECRET_KEY":
                return "fake-alpaca-secret"
            elif key == "ALPACA_BASE_URL":
                return "https://paper-api.alpaca.markets"
            return default

        mock_getenv.side_effect = mock_getenv_side_effect

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {
                "symbol": "AAPL",
                "direction": "hold",  # Use 'hold' to avoid triggering trade execution
                "confidence": 0.85,
                "reason": "Strong growth indicators",
            }
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        # Run the task with manual_test=True to bypass bot enabled gate
        analyze_post(self.post.id, manual_test=True)

        # Check that analysis was created
        analysis = Analysis.objects.get(post=self.post)
        self.assertEqual(analysis.symbol, "AAPL")
        self.assertEqual(analysis.direction, "hold")
        self.assertEqual(analysis.confidence, 0.85)

    @patch("core.tasks.tradeapi.REST")
    @patch("core.tasks.os.getenv")
    def test_execute_trade_task(self, mock_getenv, mock_tradeapi):
        """Test the execute_trade Celery task."""
        # Create analysis
        analysis = Analysis.objects.create(
            post=self.post,
            symbol="AAPL",
            direction="buy",
            confidence=0.85,
            reason="Test analysis",
        )

        # Mock environment variables and Alpaca API
        mock_getenv.side_effect = lambda key, default=None: {
            "ALPACA_API_KEY": "fake-key",
            "ALPACA_SECRET_KEY": "fake-secret",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        }.get(key, default)

        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_api.submit_order.return_value = mock_order

        mock_ticker = MagicMock()
        mock_ticker.price = 150.0
        mock_api.get_latest_trade.return_value = mock_ticker

        mock_tradeapi.return_value = mock_api

        # Run the task
        execute_trade(analysis.id)

        # Check that trade was created
        trade = Trade.objects.get(analysis=analysis)
        self.assertEqual(trade.symbol, "AAPL")
        self.assertEqual(trade.direction, "buy")
        self.assertEqual(trade.alpaca_order_id, "order-123")


class APITests(APITestCase):
    """Test REST API endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        self.trading_config = TradingConfig.objects.create(
            name="Test Config", is_active=True
        )

        self.source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

    def test_trading_config_api(self):
        """Test TradingConfig API endpoints."""
        url = reverse("tradingconfig-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_source_api(self):
        """Test Source API endpoints."""
        url = reverse("source-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    @patch("core.tasks.scrape_posts.delay")
    def test_trigger_scrape_api(self, mock_task):
        """Test manual scrape trigger API."""
        url = reverse("source-trigger-scrape", kwargs={"pk": self.source.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Scraping triggered", response.data["status"])
        mock_task.assert_called_once_with(source_id=self.source.id)

    def test_trade_summary_api(self):
        """Test trade summary API endpoint."""
        url = reverse("trade-summary")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Check summary structure
        self.assertIn("total_trades", response.data)
        self.assertIn("open_trades", response.data)
        self.assertIn("closed_trades", response.data)
        self.assertIn("total_pnl", response.data)


class AdminTests(TestCase):
    """Test Django admin interface."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="adminpass"
        )
        self.client = Client()
        self.client.login(username="admin", password="adminpass")

    def test_admin_access(self):
        """Test admin interface access."""
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_source_admin(self):
        """Test Source admin interface."""
        source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

        # Test list view
        response = self.client.get("/admin/core/source/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Source")

        # Test detail view
        response = self.client.get(f"/admin/core/source/{source.id}/change/")
        self.assertEqual(response.status_code, 200)

    def test_trading_config_admin(self):
        """Test TradingConfig admin interface."""
        config = TradingConfig.objects.create(name="Test Config", is_active=True)

        # Test list view
        response = self.client.get("/admin/core/tradingconfig/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Config")


class SourceLLMTests(TestCase):
    @patch("core.source_llm.openai.OpenAI")
    @patch("core.source_llm.requests.get")
    @patch("core.source_llm.os.getenv")
    def test_analyze_news_source_with_llm_and_build_kwargs(self, mock_getenv, mock_requests_get, mock_openai):
        mock_getenv.side_effect = lambda key, default=None: (
            "fake-key" if key == "OPENAI_API_KEY" else default
        )

        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.text = "<html><head><link rel=\"alternate\" type=\"application/rss+xml\" href=\"/rss.xml\"></head><body>News</body></html>"

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({
            "recommended_method": "api",
            "confidence_score": 0.9,
            "reasoning": ["API available"],
            "api": {
                "endpoint": "https://example.com/api/news",
                "method": "GET",
                "response_path": "articles",
                "content_field": "title",
                "url_field": "url",
                "min_score": 0
            },
            "selectors": {
                "container": ".card",
                "title": ["h3"],
                "content": ["p"],
                "link": "a"
            }
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai.return_value = mock_client

        url = "https://example.com/news"
        analysis = analyze_news_source_with_llm(url)
        self.assertIn("recommended_config", analysis)
        self.assertEqual(analysis["recommended_config"]["recommended_method"], "api")

        kwargs = build_source_kwargs_from_llm_analysis(url, "Example News", analysis)
        self.assertEqual(kwargs["scraping_method"], "api")
        self.assertIn("data_extraction_config", kwargs)

class IntegrationTests(TestCase):
    """Test integration between components."""

    def setUp(self):
        self.trading_config = TradingConfig.objects.create(
            name="Test Config", is_active=True, min_confidence_threshold=0.8, bot_enabled=True
        )

        self.source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

    @patch("core.tasks.openai.OpenAI")
    @patch("core.tasks.tradeapi.REST")
    @patch("core.tasks.os.getenv")
    def test_full_trading_workflow(self, mock_getenv, mock_tradeapi, mock_openai):
        """Test the complete workflow from post to trade."""
        # Mock environment variables
        mock_getenv.side_effect = lambda key, default=None: {
            "OPENAI_API_KEY": "fake-openai-key",
            "ALPACA_API_KEY": "fake-alpaca-key",
            "ALPACA_SECRET_KEY": "fake-alpaca-secret",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        }.get(key, default)

        # Mock OpenAI response
        mock_openai_response = MagicMock()
        mock_openai_response.choices[0].message.content = json.dumps(
            {
                "symbol": "TSLA",
                "direction": "buy",
                "confidence": 0.9,  # Above threshold
                "reason": "Very positive news about Tesla",
            }
        )

        mock_openai_client = MagicMock()
        mock_openai_client.chat.completions.create.return_value = mock_openai_response
        mock_openai.return_value = mock_openai_client

        # Mock Alpaca API
        mock_alpaca_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_alpaca_api.submit_order.return_value = mock_order

        mock_ticker = MagicMock()
        mock_ticker.price = 200.0
        mock_alpaca_api.get_latest_trade.return_value = mock_ticker

        mock_tradeapi.return_value = mock_alpaca_api

        # Create post
        post = Post.objects.create(
            source=self.source,
            content="Tesla announces breakthrough in battery technology",
            url="https://example.com/tesla-news",
        )

        # Trigger analysis with manual_test=True to bypass bot enabled gate
        analyze_post(post.id, manual_test=True)

        # Check that analysis was created
        analysis = Analysis.objects.get(post=post)
        self.assertEqual(analysis.symbol, "TSLA")
        self.assertEqual(analysis.direction, "buy")
        self.assertEqual(analysis.confidence, 0.9)

        # Check that trade was created (should be triggered automatically due to high confidence)
        trade = Trade.objects.get(analysis=analysis)
        self.assertEqual(trade.symbol, "TSLA")
        self.assertEqual(trade.direction, "buy")
        self.assertEqual(trade.alpaca_order_id, "order-123")


class DashboardTests(TestCase):
    """Test dashboard functionality."""

    def setUp(self):
        self.client = Client()
        # Staff-only dashboard now requires login
        self.user = User.objects.create_user(username="staff", password="staffpass", is_staff=True)
        self.client.login(username="staff", password="staffpass")

    def test_dashboard_access(self):
        """Test dashboard page access."""
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "News Trader Dashboard")

    def test_alerts_page_includes_bot_status(self):
        """Alerts page should receive correct bot status in context for navbar."""
        # Ensure active config exists with bot_enabled False -> badge should show disabled text
        TradingConfig.objects.update_or_create(
            is_active=True,
            defaults={"name": "Active", "bot_enabled": False},
        )
        resp = self.client.get("/alerts/")
        self.assertEqual(resp.status_code, 200)
        # Navbar badge text appears when bot is disabled
        self.assertContains(resp, "BOT DISABLED")

    def test_alerts_page(self):
        # Ensure alerts page renders and can save settings
        response = self.client.get("/alerts/")
        self.assertEqual(response.status_code, 200)

        resp_post = self.client.post(
            "/alerts/",
            {
                "enabled": "on",
                "bot_status_enabled": "on",
                "order_open_enabled": "on",
                "order_close_enabled": "on",
                "trading_limit_enabled": "on",
            },
        )
        self.assertEqual(resp_post.status_code, 302)
        settings = AlertSettings.objects.order_by("-created_at").first()
        self.assertTrue(settings.enabled)

    


class ErrorHandlingTests(TestCase):
    """Test error handling scenarios."""

    def setUp(self):
        self.source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

        self.post = Post.objects.create(
            source=self.source, content="Test content", url="https://example.com/post/1"
        )

    @patch("core.tasks.openai.OpenAI")
    @patch("core.tasks.os.getenv")
    def test_analyze_post_no_api_key(self, mock_getenv, mock_openai):
        """Test analyze_post when OpenAI API key is missing."""
        mock_getenv.return_value = None  # No API key

        # This should handle the error gracefully
        analyze_post(self.post.id)

        # Should not create an analysis
        self.assertFalse(Analysis.objects.filter(post=self.post).exists())

    @patch("core.tasks.openai.OpenAI")
    @patch("core.tasks.os.getenv")
    def test_analyze_post_invalid_json(self, mock_getenv, mock_openai):
        """Test analyze_post when LLM returns invalid JSON."""
        mock_getenv.return_value = "fake-api-key"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Invalid JSON response"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        # Run the task with manual_test=True to bypass bot enabled check
        analyze_post(self.post.id, manual_test=True)

        # Should create an error analysis
        analysis = Analysis.objects.get(post=self.post)
        self.assertEqual(analysis.symbol, "ERROR")
        self.assertEqual(analysis.direction, "hold")
        self.assertIn("invalid JSON", analysis.reason)


class ExternalIntegrationTests(TestCase):
    """
    Integration tests that verify real external connections.
    These tests use actual environment variables and skip if credentials aren't available.
    """

    def setUp(self):
        self.trading_config = TradingConfig.objects.create(
            name="Integration Test Config",
            is_active=True,
            bot_enabled=True,
            min_confidence_threshold=0.7,
        )

    @skipIf(not os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY not set - skipping real API test")
    def test_openai_api_real_connection(self):
        """Test actual OpenAI API connection and functionality."""
        print("\n🔗 Testing real OpenAI API connection...")
        
        import openai
        
        api_key = os.getenv("OPENAI_API_KEY")
        self.assertIsNotNone(api_key, "OpenAI API key should be available")
        
        try:
            # Test actual API call with simple prompt
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Respond with valid JSON only."},
                    {"role": "user", "content": 'Respond with: {"status": "success", "test": true}'}
                ],
                response_format={"type": "json_object"},
                max_tokens=50,
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            self.assertEqual(data.get("status"), "success")
            self.assertTrue(data.get("test"))
            print("✅ OpenAI API connection successful")
            
        except Exception as e:
            self.fail(f"OpenAI API connection failed: {e}")

    @skipIf(
        not all([os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")]), 
        "Alpaca API credentials not set - skipping real API test"
    )
    def test_alpaca_api_real_connection(self):
        """Test actual Alpaca API connection and account access."""
        print("\n🔗 Testing real Alpaca API connection...")
        
        import alpaca_trade_api as tradeapi
        
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        self.assertIsNotNone(api_key, "Alpaca API key should be available")
        self.assertIsNotNone(secret_key, "Alpaca secret key should be available")
        
        try:
            # Test actual API connection
            api = tradeapi.REST(api_key, secret_key, base_url=base_url)
            
            # Get account info to verify connection
            account = api.get_account()
            self.assertIsNotNone(account)
            self.assertIsNotNone(account.id)
            
            # Verify account is active
            self.assertEqual(account.status, "ACTIVE")
            
            # Test getting market data for a known symbol
            latest_trade = api.get_latest_trade("AAPL")
            self.assertIsNotNone(latest_trade)
            self.assertIsNotNone(latest_trade.price)
            self.assertGreater(latest_trade.price, 0)
            
            print(f"✅ Alpaca API connection successful - Account: {account.id}")
            print(f"   Account Status: {account.status}")
            print(f"   AAPL Latest Price: ${latest_trade.price}")
            
        except Exception as e:
            self.fail(f"Alpaca API connection failed: {e}")

    @skipIf(not os.getenv("TELEGRAM_BOT_TOKEN"), "TELEGRAM_BOT_TOKEN not set - skipping real bot test")
    def test_telegram_bot_real_connection(self):
        """Test actual Telegram bot connection and basic functionality."""
        print("\n🔗 Testing real Telegram bot connection...")
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.assertIsNotNone(bot_token, "Telegram bot token should be available")
        
        try:
            # Test the connection using simple HTTP request (no async)
            import httpx
            
            response = httpx.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
            self.assertEqual(response.status_code, 200)
            
            bot_info = response.json()
            self.assertTrue(bot_info.get("ok"))
            self.assertIsNotNone(bot_info.get("result", {}).get("username"))
            
            username = bot_info["result"]["username"]
            bot_id = bot_info["result"]["id"]
            
            print(f"✅ Telegram bot connection successful - @{username} (ID: {bot_id})")
            
        except Exception as e:
            self.fail(f"Telegram bot connection failed: {e}")

    def test_playwright_browser_real_functionality(self):
        """Test actual Playwright browser installation and basic scraping."""
        print("\n🔗 Testing real Playwright browser functionality...")
        
        try:
            from core.browser_manager import get_managed_browser_page
            import threading
            import queue
            
            # Run Playwright in a separate thread to avoid async/sync conflicts
            result_queue = queue.Queue()
            
            def run_playwright_test():
                try:
                    # Test with a simple, reliable page
                    test_url = "https://httpbin.org/html"
                    
                    with get_managed_browser_page() as page:
                        # Set reasonable timeouts
                        page.set_default_timeout(10000)
                        
                        # Navigate to test page
                        page.goto(test_url, timeout=15000)
                        
                        # Check that page loaded
                        title = page.title()
                        
                        # Check that we can find HTML elements
                        h1_elements = page.query_selector_all("h1")
                        
                        # Get page content
                        content = page.content()
                        
                        result_queue.put({
                            'success': True,
                            'title': title,
                            'h1_count': len(h1_elements),
                            'has_html': "html" in content.lower(),
                            'has_melville': "Herman Melville" in content
                        })
                        
                except Exception as e:
                    result_queue.put({'success': False, 'error': str(e)})
            
            # Run Playwright test in thread
            thread = threading.Thread(target=run_playwright_test)
            thread.start()
            thread.join(timeout=30)  # 30 second timeout
            
            if thread.is_alive():
                self.fail("Playwright test timed out after 30 seconds")
            
            # Get results
            result = result_queue.get_nowait()
            
            if not result['success']:
                self.fail(f"Playwright browser test failed: {result['error']}")
            
            # Verify results
            self.assertIsNotNone(result['title'])
            self.assertGreater(result['h1_count'], 0)
            self.assertTrue(result['has_html'])
            self.assertTrue(result['has_melville'])
            
            print("✅ Playwright browser functionality successful")
            print(f"   Page title: {result['title']}")
            print(f"   Found {result['h1_count']} H1 elements")
            
        except Exception as e:
            self.fail(f"Playwright browser test failed: {e}")

    @skipIf(
        not all([os.getenv("OPENAI_API_KEY"), os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")]),
        "OpenAI or Alpaca API credentials not set - skipping full integration test"
    )
    def test_full_real_trading_workflow(self):
        """Test complete real workflow: OpenAI analysis → Alpaca trade preparation."""
        print("\n🔗 Testing full real trading workflow...")
        
        # Create a test post
        source = Source.objects.create(
            name="Integration Test Source",
            url="https://example.com",
            scraping_method="web",
        )
        
        post = Post.objects.create(
            source=source,
            content="Apple reports strong quarterly earnings with record iPhone sales",
            url="https://example.com/test-post",
        )
        
        try:
            # Run real analysis with OpenAI (but don't execute actual trade)
            import openai
            import alpaca_trade_api as tradeapi
            
            # Test OpenAI analysis
            api_key = os.getenv("OPENAI_API_KEY")
            client = openai.OpenAI(api_key=api_key)
            
            prompt = """You are a financial analyst. Analyze the given text for potential financial impact on a stock. 
Respond with a JSON object: { "symbol": "STOCK_SYMBOL", "direction": "buy", "confidence": 0.87, "reason": "Explanation" }. 
Direction can be 'buy', 'sell', or 'hold'. Confidence is a float between 0 and 1."""
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": post.content}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=200,
            )
            
            content = response.choices[0].message.content
            llm_output = json.loads(content)
            
            # Create analysis record
            analysis = Analysis.objects.create(
                post=post,
                symbol=llm_output.get("symbol", "UNKNOWN"),
                direction=llm_output.get("direction", "hold"),
                confidence=llm_output.get("confidence", 0.0),
                reason=llm_output.get("reason", "No reason provided"),
                raw_llm_response=content,
                trading_config_used=self.trading_config,
            )
            
            # Verify OpenAI response format
            self.assertIn("symbol", llm_output)
            self.assertIn("direction", llm_output)
            self.assertIn("confidence", llm_output)
            self.assertIsInstance(llm_output["confidence"], (int, float))
            
            # Test Alpaca API connection (but don't submit real orders)
            alpaca_api_key = os.getenv("ALPACA_API_KEY")
            alpaca_secret = os.getenv("ALPACA_SECRET_KEY")
            alpaca_base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
            
            api = tradeapi.REST(alpaca_api_key, alpaca_secret, base_url=alpaca_base_url)
            
            # Verify we can get account info
            account = api.get_account()
            self.assertIsNotNone(account)
            
            # If analysis suggests a trade, verify we can get market data for the symbol
            if analysis.direction in ["buy", "sell"] and analysis.symbol != "UNKNOWN":
                try:
                    latest_trade = api.get_latest_trade(analysis.symbol)
                    self.assertIsNotNone(latest_trade)
                    self.assertGreater(latest_trade.price, 0)
                    print(f"   Market data for {analysis.symbol}: ${latest_trade.price}")
                except Exception as symbol_error:
                    print(f"   Note: Could not get market data for {analysis.symbol}: {symbol_error}")
            
            print("✅ Full real trading workflow successful")
            print(f"   OpenAI Analysis: {analysis.symbol} - {analysis.direction} (confidence: {analysis.confidence})")
            print(f"   Alpaca Account: {account.id} ({account.status})")
            print(f"   Analysis reason: {analysis.reason}")
            
        except Exception as e:
            self.fail(f"Full real trading workflow failed: {e}")

    def test_real_web_scraping_workflow(self):
        """Test real web scraping with Playwright on a simple, reliable page."""
        print("\n🔗 Testing real web scraping workflow...")
        
        try:
            # Create a test source pointing to a simple, reliable page
            source = Source.objects.create(
                name="HTTPBin Test Source",
                url="https://httpbin.org/html",
                scraping_method="web",
                scraping_enabled=True,
            )
            
            from core.browser_manager import get_managed_browser_page
            import threading
            import queue
            
            # Run Playwright in a separate thread to avoid async/sync conflicts
            result_queue = queue.Queue()
            
            def run_scraping_test():
                try:
                    # Test the scraping functionality
                    with get_managed_browser_page() as page:
                        page.set_default_timeout(10000)
                        page.goto(source.url, timeout=15000)
                        
                        # Wait for page to load
                        page.wait_for_selector("body", timeout=5000)
                        
                        # Look for content typical of news-like elements
                        headline_selectors = ["h1", "h2", "h3", "p"]
                        found_elements = []
                        
                        for selector in headline_selectors:
                            elements = page.query_selector_all(selector)
                            for element in elements[:5]:  # Limit to prevent too many
                                try:
                                    text = element.inner_text().strip()
                                    if text and len(text) > 10:  # Meaningful content
                                        found_elements.append({
                                            'text': text[:100],  # Limit length
                                            'selector': selector,
                                            'url': source.url
                                        })
                                except Exception:
                                    continue
                        
                        # Verify we found the expected content from httpbin.org/html
                        page_content = page.content()
                        has_melville = "Herman Melville" in page_content
                        
                        result_queue.put({
                            'success': True,
                            'found_elements': found_elements,
                            'has_melville': has_melville
                        })
                        
                except Exception as e:
                    result_queue.put({'success': False, 'error': str(e)})
            
            # Run scraping test in thread
            thread = threading.Thread(target=run_scraping_test)
            thread.start()
            thread.join(timeout=30)  # 30 second timeout
            
            if thread.is_alive():
                self.fail("Scraping test timed out after 30 seconds")
            
            # Get results
            result = result_queue.get_nowait()
            
            if not result['success']:
                self.fail(f"Real web scraping workflow failed: {result['error']}")
            
            # Verify results
            found_elements = result['found_elements']
            self.assertGreater(len(found_elements), 0, "Should find some text elements on the page")
            self.assertTrue(result['has_melville'])
            
            print("✅ Real web scraping workflow successful")
            print(f"   Found {len(found_elements)} content elements")
            for elem in found_elements[:3]:  # Show first 3
                print(f"   - {elem['selector']}: {elem['text'][:50]}...")
                
        except Exception as e:
            self.fail(f"Real web scraping workflow failed: {e}")


if __name__ == "__main__":
    import unittest

    unittest.main()
