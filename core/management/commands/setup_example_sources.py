from django.core.management.base import BaseCommand
from core.models import Source, TradingConfig


class Command(BaseCommand):
    help = "Sets up example source configurations for NewsAPI and Truth Social"

    def handle(self, *args, **options):
        # Create default trading configuration
        trading_config, created = TradingConfig.objects.get_or_create(
            name="Default Trading Configuration",
            defaults={
                "is_active": True,
                "trading_enabled": True,
                "default_position_size": 100.0,
                "max_position_size": 1000.0,
                "stop_loss_percentage": 5.0,
                "take_profit_percentage": 10.0,
                "min_confidence_threshold": 0.7,
                "max_daily_trades": 10,
                "llm_model": "gpt-3.5-turbo",
                "market_hours_only": True,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created default trading configuration: {trading_config.name}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Trading configuration already exists: {trading_config.name}"
                )
            )

        # Create NewsAPI source configuration
        newsapi_source, created = Source.objects.get_or_create(
            name="NewsAPI - Financial News",
            url="https://newsapi.org/v2/everything",
            defaults={
                "description": "NewsAPI service for fetching financial news articles",
                "scraping_method": "api",
                "api_endpoint": "https://newsapi.org/v2/everything",
                "api_key_field": "NEWSAPI_KEY",  # Environment variable name
                "request_type": "GET",
                "request_params": {
                    "q": 'stock market OR NYSE OR NASDAQ OR "financial news" OR earnings',
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": 20,
                },
                "data_extraction_config": {
                    "response_path": "articles",  # JSON path to articles array
                    "content_field": "title",  # or 'description' or combined
                    "url_field": "url",
                    "title_field": "title",
                    "published_field": "publishedAt",
                },
                "scraping_enabled": True,
                "scraping_interval_minutes": 15,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created NewsAPI source: {newsapi_source.name}")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"NewsAPI source already exists: {newsapi_source.name}"
                )
            )

        # Create Truth Social API source configuration
        truth_social_source, created = Source.objects.get_or_create(
            name="Truth Social - Financial Posts",
            url="https://truthsocial.com/api/v1/timelines/public",
            defaults={
                "description": "Truth Social API for fetching financial-related posts",
                "scraping_method": "api",
                "api_endpoint": "https://truthsocial.com/api/v1/timelines/public",
                "api_key_field": "TRUTH_SOCIAL_API_KEY",  # Environment variable name
                "request_type": "GET",
                "request_params": {"limit": 20, "only_media": False},
                "data_extraction_config": {
                    "response_path": "",  # Root array
                    "content_field": "content",
                    "url_field": "url",
                    "filter_keywords": [
                        "stock",
                        "market",
                        "NYSE",
                        "NASDAQ",
                        "$",
                        "earnings",
                        "financial",
                    ],
                },
                "scraping_enabled": False,  # Disabled by default
                "scraping_interval_minutes": 10,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created Truth Social source: {truth_social_source.name}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Truth Social source already exists: {truth_social_source.name}"
                )
            )

        # Create Reddit scraping source
        reddit_source, created = Source.objects.get_or_create(
            name="Reddit - r/stocks",
            url="https://www.reddit.com/r/stocks/hot.json",
            defaults={
                "description": "Reddit r/stocks subreddit for stock discussions",
                "scraping_method": "api",
                "api_endpoint": "https://www.reddit.com/r/stocks/hot.json",
                "api_key_field": "REDDIT_USER_AGENT",  # User agent header
                "request_type": "GET",
                "request_params": {"limit": 25},
                "data_extraction_config": {
                    "response_path": "data.children",
                    "content_field": "data.title",
                    "url_field": "data.url",
                    "score_field": "data.score",
                    "min_score": 10,  # Only posts with 10+ upvotes
                },
                "scraping_enabled": True,
                "scraping_interval_minutes": 20,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created Reddit source: {reddit_source.name}")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Reddit source already exists: {reddit_source.name}"
                )
            )

        # Create Yahoo Finance RSS source
        yahoo_finance_source, created = Source.objects.get_or_create(
            name="Yahoo Finance - Market News RSS",
            url="https://feeds.finance.yahoo.com/rss/2.0/headline",
            defaults={
                "description": "Yahoo Finance RSS feed for market news",
                "scraping_method": "web",
                "data_extraction_config": {
                    "content_selector": "item > title",
                    "url_selector": "item > link",
                    "description_selector": "item > description",
                    "date_selector": "item > pubDate",
                },
                "scraping_enabled": True,
                "scraping_interval_minutes": 30,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created Yahoo Finance source: {yahoo_finance_source.name}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Yahoo Finance source already exists: {yahoo_finance_source.name}"
                )
            )

        # Create AlphaVantage News source
        alphavantage_source, created = Source.objects.get_or_create(
            name="AlphaVantage - Market News",
            url="https://www.alphavantage.co/query",
            defaults={
                "description": "AlphaVantage News & Sentiment API",
                "scraping_method": "api",
                "api_endpoint": "https://www.alphavantage.co/query",
                "api_key_field": "ALPHAVANTAGE_API_KEY",
                "request_type": "GET",
                "request_params": {
                    "function": "NEWS_SENTIMENT",
                    "tickers": "SPY,QQQ,AAPL,GOOGL,MSFT",
                    "limit": 50,
                },
                "data_extraction_config": {
                    "response_path": "feed",
                    "content_field": "title",
                    "url_field": "url",
                    "sentiment_field": "overall_sentiment_score",
                    "relevance_field": "relevance_score",
                },
                "scraping_enabled": False,  # Requires API key
                "scraping_interval_minutes": 60,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created AlphaVantage source: {alphavantage_source.name}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"AlphaVantage source already exists: {alphavantage_source.name}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS("\n=== Source Configuration Setup Complete! ===")
        )
        self.stdout.write(self.style.SUCCESS("Next steps:"))
        self.stdout.write("1. Set up environment variables for API keys:")
        self.stdout.write("   - NEWSAPI_KEY: Get from https://newsapi.org/")
        self.stdout.write(
            "   - TRUTH_SOCIAL_API_KEY: Get from Truth Social developer portal"
        )
        self.stdout.write("   - REDDIT_USER_AGENT: Your app name/version")
        self.stdout.write(
            "   - ALPHAVANTAGE_API_KEY: Get from https://www.alphavantage.co/"
        )
        self.stdout.write("2. Enable/disable sources via Django admin")
        self.stdout.write("3. Configure trading parameters in TradingConfig")
        self.stdout.write("4. Start Celery workers and beat scheduler")
        self.stdout.write("5. Monitor trades via the dashboard")
