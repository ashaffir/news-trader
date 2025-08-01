from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token
from core.models import Source, Post, Analysis, Trade, TradingConfig, ApiResponse
from core.tasks import analyze_post, execute_trade, scrape_posts
import json


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
            name="Test Config", is_active=True, min_confidence_threshold=0.7
        )

        self.source = Source.objects.create(
            name="Test Source", url="https://example.com", scraping_method="web"
        )

        self.post = Post.objects.create(
            source=self.source,
            content="Apple stock shows strong growth potential",
            url="https://example.com/post/1",
        )

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

        # Run the task
        analyze_post(self.post.id)

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


class IntegrationTests(TestCase):
    """Test integration between components."""

    def setUp(self):
        self.trading_config = TradingConfig.objects.create(
            name="Test Config", is_active=True, min_confidence_threshold=0.8
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

        # Trigger analysis
        analyze_post(post.id)

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

    def test_dashboard_access(self):
        """Test dashboard page access."""
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "News Trader Dashboard")

    


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

        # Run the task
        analyze_post(self.post.id)

        # Should create an error analysis
        analysis = Analysis.objects.get(post=self.post)
        self.assertEqual(analysis.symbol, "ERROR")
        self.assertEqual(analysis.direction, "hold")
        self.assertIn("invalid JSON", analysis.reason)


if __name__ == "__main__":
    import unittest

    unittest.main()
