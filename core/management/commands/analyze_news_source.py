"""
Django management command to analyze and configure new news sources using an LLM.
"""

from django.core.management.base import BaseCommand
from core.models import Source
from core.source_llm import (
    analyze_news_source_with_llm,
    build_source_kwargs_from_llm_analysis,
)
import json


class Command(BaseCommand):
    help = "Analyze a news source via LLM and optionally create a configured Source"

    def add_arguments(self, parser):
        parser.add_argument("url", type=str, help="URL of the news source to analyze")
        parser.add_argument(
            "--create-source",
            action="store_true",
            help="Create a Source using the LLM-recommended configuration",
        )
        parser.add_argument(
            "--name",
            type=str,
            help="Source name (required with --create-source)",
        )
        parser.add_argument(
            "--save-analysis",
            type=str,
            help="Save raw LLM analysis JSON to file",
        )
        parser.add_argument(
            "--test-scrape",
            action="store_true",
            help="After creation, run a quick scrape to validate configuration",
        )

    def handle(self, *args, **options):
        url = options["url"]
        self.stdout.write(self.style.SUCCESS(f"🔍 LLM analyzing news source: {url}"))

        try:
            analysis = analyze_news_source_with_llm(url)
            self._display_analysis_results(analysis)

            if options.get("save_analysis"):
                with open(options["save_analysis"], "w") as f:
                    json.dump(analysis, f, indent=2)
                self.stdout.write(
                    self.style.SUCCESS(f"📁 Analysis saved to: {options['save_analysis']}")
                )

            if options.get("create_source"):
                name = options.get("name")
                if not name:
                    self.stdout.write(
                        self.style.ERROR("❌ --name is required when using --create-source")
                    )
                    return

                source_kwargs = build_source_kwargs_from_llm_analysis(url, name, analysis)
                source = Source.objects.create(**source_kwargs)
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Created source: {source.name} (ID: {source.id})")
                )

                if options.get("test_scrape"):
                    self._test_scrape(source)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))
            raise

    def _display_analysis_results(self, analysis):
        config = analysis["recommended_config"]

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.HTTP_INFO("📊 LLM ANALYSIS RESULTS"))
        self.stdout.write("=" * 60)

        self.stdout.write(f"🌐 Domain: {analysis['domain']}")
        self.stdout.write(f"📅 Analyzed: {analysis['analyzed_at']}")

        self.stdout.write(f"\n🎯 RECOMMENDED: {config['recommended_method'].upper()}")
        self.stdout.write(f"🎲 Confidence: {config.get('confidence_score', 0):.2f}")

        self.stdout.write("\n🧠 REASONING:")
        for reason in config.get("reasoning", []):
            self.stdout.write(f"  • {reason}")

        if analysis.get("rss_feeds"):
            self.stdout.write(f"\n📡 RSS FEEDS ({len(analysis['rss_feeds'])}):")
            for feed in analysis["rss_feeds"]:
                self.stdout.write(f"  • {feed['title']}: {feed['url']}")

        if analysis.get("api_endpoints"):
            self.stdout.write(f"\n🔌 API ENDPOINTS ({len(analysis['api_endpoints'])}):")
            for api in analysis["api_endpoints"]:
                self.stdout.write(f"  • {api['type']}: {api['url']}")

        if config.get("selectors"):
            sels = config["selectors"]
            self.stdout.write("\n🎯 SELECTORS:")
            self.stdout.write(f"  Container: {sels.get('container', 'N/A')}")
            self.stdout.write(f"  Title: {sels.get('title', 'N/A')}")
            self.stdout.write(f"  Content: {sels.get('content', 'N/A')}")
            self.stdout.write(f"  Link: {sels.get('link', 'N/A')}")

    def _test_scrape(self, source):
        self.stdout.write(f"\n🧪 Testing scrape for: {source.name}")
        try:
            from core.tasks import _scrape_source

            self.stdout.write("🔄 Running test scrape...")
            _scrape_source(source)

            from core.models import Post
            posts = Post.objects.filter(source=source).order_by("-created_at")[:5]
            if posts:
                self.stdout.write(self.style.SUCCESS(f"✅ Found {posts.count()} posts:"))
                for i, post in enumerate(posts, 1):
                    title = post.content.split("\n")[0][:60]
                    self.stdout.write(f"  {i}. {title}...")
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  No posts created. Verify configuration."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Test scrape failed: {e}"))

