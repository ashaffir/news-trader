import os
import openai
import alpaca_trade_api as tradeapi
import json
import requests
from bs4 import BeautifulSoup
from celery import shared_task
from core.browser_manager import get_managed_browser_page, get_browser_pool_stats
import asyncio
from pathlib import Path

from .models import Source, ApiResponse, Post, Analysis, Trade, TradingConfig, ActivityLog, AlertSettings, TwitterSession
from .twitter_scraper import scrape_twitter_profile

# Health monitoring will be defined in this file for proper Celery registration
from django.utils import timezone
from django.db.models import Q
import logging
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# =============================
# Database Backup
# =============================

@shared_task
def backup_database(backup_dir: str | None = None):
    """Create a compressed PostgreSQL database backup on the local machine.

    The backup directory defaults to `<project_root>/backups`. You can override
    by passing an absolute path in `backup_dir`.
    """
    try:
        from .utils.db_backup import create_database_backup, get_default_backup_dir

        target_dir = Path(backup_dir) if backup_dir else get_default_backup_dir()
        backup_path = create_database_backup(target_dir)

        ActivityLog.objects.create(
            activity_type="system_event",
            message="Database backup completed",
            data={
                "backup_path": str(backup_path),
                "timestamp": timezone.now().isoformat(),
            },
        )
        logger.info(f"Database backup created at {backup_path}")
        return {"status": "success", "path": str(backup_path)}
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        ActivityLog.objects.create(
            activity_type="system_event",
            message="Database backup failed",
            data={"error": str(e), "timestamp": timezone.now().isoformat()},
        )
        return {"status": "error", "error": str(e)}

def _is_async_context() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False

def _run_db_call_in_thread(fn):
    import threading
    import queue
    result_q = queue.Queue()
    def _runner():
        try:
            from django.db import connection
            connection.ensure_connection()
            result_q.put((True, fn()))
        except Exception as e:
            result_q.put((False, e))
    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    ok, payload = result_q.get()
    if ok:
        return payload
    raise payload
def _get_recent_hours_default() -> int:
    try:
        return int(os.getenv("SCRAPE_RECENT_HOURS", "24"))
    except Exception:
        return 24


def _looks_like_article_url(url: str) -> bool:
    """Heuristic to detect article-like URLs.

    Works across many sites and reduces noise from nav/about/contact/tag pages.
    """
    if not url:
        return False
    u = url.lower()
    positives = [
        "/20",  # year-based path e.g., /2025/
        "/news/",
        "/article/",
        "/story/",
        "/reports/",
        "/business/",
    ]
    negatives = [
        "#",
        "javascript:",
        "/tag/",
        "/tags/",
        "/category/",
        "/author/",
        "/about",
        "/contact",
        "/subscribe",
        ".pdf",
        ".jpg",
        ".png",
        ".gif",
        "/privacy",
        "/terms",
    ]
    if any(n in u for n in negatives):
        return False
    return any(p in u for p in positives)



def _normalize_content_for_comparison(content):
    """Normalize content for duplicate detection"""
    # Extract title (first line) and normalize it
    lines = content.strip().split('\n')
    title = lines[0] if lines else ""
    
    # Remove common prefixes/suffixes and normalize whitespace
    title = title.strip()
    
    # Remove common news site patterns
    patterns_to_remove = [
        "Live updates", "Breaking:", "BREAKING:", "UPDATE:", "EXCLUSIVE:",
        "- CNN", "- BBC", "- Reuters", "- AP", "| Reuters", "| AP News",
        "- CNBC", "| CNBC", "| NBC News"
    ]
    
    for pattern in patterns_to_remove:
        title = title.replace(pattern, "").strip()
    
    # Remove extra whitespace and convert to lowercase for comparison
    title = ' '.join(title.split()).lower()
    
    return title


def _is_duplicate_content(content, source, similarity_threshold=0.85):
    """
    Check if content is a duplicate based on title similarity and URL
    
    Args:
        content: The article content to check
        source: Source object
        similarity_threshold: Minimum similarity to consider as duplicate (0.0-1.0)
    
    Returns:
        True if duplicate found, False otherwise
    """
    normalized_new = _normalize_content_for_comparison(content)
    
    if not normalized_new:
        return False
    
    # Check against recent posts from the same source (last 7 days)
    recent_cutoff = timezone.now() - timedelta(days=7)
    recent_posts = Post.objects.filter(
        source=source,
        created_at__gte=recent_cutoff
    ).values_list('content', flat=True)
    
    for existing_content in recent_posts:
        normalized_existing = _normalize_content_for_comparison(existing_content)
        
        if not normalized_existing:
            continue
            
        # Simple similarity check using set intersection
        words_new = set(normalized_new.split())
        words_existing = set(normalized_existing.split())
        
        if not words_new or not words_existing:
            continue
        
        # Calculate Jaccard similarity
        intersection = words_new.intersection(words_existing)
        union = words_new.union(words_existing)
        
        similarity = len(intersection) / len(union) if union else 0
        
        if similarity >= similarity_threshold:
            logger.info(f"Duplicate content detected (similarity: {similarity:.2f}): {normalized_new[:50]}...")
            return True
    
    return False


def format_activity_message(message_type, data):
    """Format activity message for consistent display."""
    # Normalize common fields
    def _num(val, default=0.0):
        try:
            return float(val)
        except Exception:
            return float(default)

    pnl_value = data.get('pnl')
    if pnl_value is None:
        pnl_value = data.get('realized_pnl')
    pnl_value = _num(pnl_value, 0.0)

    pnl_percent_value = data.get('pnl_percent')
    try:
        pnl_percent_value = None if pnl_percent_value is None else float(pnl_percent_value)
    except Exception:
        pnl_percent_value = None

    messages = {
        'new_post': f"📰 New post from {data.get('source', 'Unknown')}: {data.get('content_preview', '')[:100]}...",
        'analysis_complete': f"🧠 Analysis: {data.get('symbol', 'N/A')} {data.get('direction', '').upper()} ({round(data.get('confidence', 0) * 100)}% confidence)",
        'trade_executed': f"💰 Trade: {data.get('direction', '').upper()} {data.get('quantity', 0)} {data.get('symbol', 'N/A')} @ ${data.get('price', 0)}",
        'trade_closed': (
            f"🎯 Trade closed: {data.get('symbol', 'N/A')} P&L: ${pnl_value:.2f}"
            + (f" ({pnl_percent_value:+.1f}%)" if pnl_percent_value is not None else "")
        ),
        'trade_close_requested': f"🚨 Close request: {data.get('symbol', 'N/A')} order submitted (ID: {data.get('order_id', 'N/A')})",
        'scraper_error': f"⚠️ Scraping error from {data.get('source', 'Unknown')}: {data.get('error', 'Unknown error')}",
        'scraper_status': f"🔄 {data.get('status', 'Scraper status update')}",
        'trade_status': f"📊 {data.get('symbol', 'N/A')} - {data.get('status', 'Status update')}" if 'TP/SL updated' in data.get('status', '') else f"📊 {data.get('status', 'Status update')}",
        'trade_rejected': f"❌ Trade rejected for {data.get('symbol', '')}: {data.get('reason', 'Limit reached')}",
    }
    return messages.get(message_type, f"🔄 Update: {data}")


def send_dashboard_update(message_type, data):
    """Save activity update to database for polling-based UI updates."""
    def _write_update():
        # Wrap all DB/alert work in a function that can run in a clean thread
        try:
            message = format_activity_message(message_type, data)
            ActivityLog.objects.create(
                activity_type=message_type,
                message=message,
                data=data
            )
            logger.debug(f"Activity logged to database: {message_type}")
            try:
                from .utils.telegram import send_telegram_message, is_alert_enabled
                logger.debug("Alert dispatch gate check for type=%s", message_type)
                if is_alert_enabled(message_type):
                    logger.info("Dispatching Telegram alert for type=%s", message_type)
                    sent = send_telegram_message(message)
                    logger.info("Telegram alert sent=%s type=%s", sent, message_type)
                else:
                    logger.info("Telegram alert disabled by settings for type=%s", message_type)
            except Exception as notify_error:
                logger.warning(f"Alert dispatch failed for {message_type}: {notify_error}")
        except Exception as e:
            logger.error(f"Failed to save activity update ({message_type}): {e}")

    # If running within an asyncio event loop thread, offload to a separate thread
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if loop_running:
        import threading
        t = threading.Thread(target=_write_update, daemon=True)
        t.start()
        t.join()
    else:
        _write_update()


def _is_simulated_post(post):
    """Check if a post is a simulated/error post that should not be analyzed by LLM."""
    # Check URL pattern
    if post.url and post.url.startswith("simulated://"):
        return True
    
    # Check content pattern
    if post.content and post.content.startswith("Simulated post from"):
        return True
    
    return False


def _create_simulated_post(source, error_message, method):
    # Make simulated URLs clearly distinct and non-browsable
    simulated_url = f"simulated://{source.name.replace(' ', '_')}/{method}/{hashlib.md5(error_message.encode()).hexdigest()}/{os.urandom(5).hex()}"
    simulated_content = f"Simulated post from {source.name} via {method} due to error: {error_message}. This is a placeholder for testing downstream processes."

    post = Post.objects.create(
        source=source, content=simulated_content, url=simulated_url
    )
    logger.info(f"Simulated post created: {post.url}")
    send_dashboard_update(
        "new_post",
        {
            "source": source.name,
            "content_preview": simulated_content[:100] + "...",
            "url": simulated_url,
            "post_id": post.id,
            "simulated": True,
        },
    )
    # Do not queue analysis for simulated posts to avoid wasted jobs
    # analyze_post will skip simulated posts anyway


def _scrape_rss_feed(source):
    """Parse RSS feeds for financial news"""
    try:
        import feedparser
        from datetime import datetime, timedelta
        
        logger.info(f"Parsing RSS feed from {source.url}")
        
        # Parse RSS feed
        feed = feedparser.parse(source.url)
        
        if feed.bozo:
            logger.warning(f"RSS feed may have issues: {source.url}")
        
        if not feed.entries:
            logger.warning(f"No entries found in RSS feed: {source.url}")
            return
            
        # Get only recent entries (configurable)
        cutoff_time = datetime.now() - timedelta(hours=_get_recent_hours_default())
        new_posts_count = 0
        
        for entry in feed.entries:  # Process all RSS entries
            try:
                # Extract entry data
                title = entry.get('title', 'No title')
                link = entry.get('link', '')
                summary = entry.get('summary', entry.get('description', ''))
                
                # Parse publication date
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6])
                
                # Skip old entries
                if published and published < cutoff_time:
                    continue
                    
                # Create content from title and summary
                content = f"{title}\n\n{summary}"
                
                # Check for duplicates by URL and content similarity
                if link:
                    url_exists = Post.objects.filter(url=link).exists()
                    content_duplicate = _is_duplicate_content(content, source)
                    
                    if url_exists:
                        logger.debug(f"Skipping RSS post - URL already exists: {link}")
                        continue
                    elif content_duplicate:
                        logger.debug(f"Skipping RSS post - similar content: {title[:50]}...")
                        continue
                    post = Post.objects.create(
                        source=source,
                        content=content,
                        url=link
                    )
                    
                    logger.info(f"New RSS post from {source.name}: {title[:50]}...")
                    send_dashboard_update(
                        "new_post",
                        {
                            "source": source.name,
                            "content_preview": content[:100] + "...",
                            "url": link,
                            "post_id": post.id,
                        },
                    )
                    analyze_post.delay(post.id)
                    new_posts_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing RSS entry: {e}")
                continue
                
        logger.info(f"RSS parsing completed for {source.name}: {new_posts_count} new posts")
        
    except Exception as e:
        logger.error(f"Error parsing RSS feed {source.url}: {e}")
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "rss"}
        )
        _create_simulated_post(source, str(e), "rss")


def _get_site_specific_selectors(url):
    """Get site-specific selectors based on URL domain"""
    site_configs = {
        'apnews.com': {
            'container': '.PagePromo',
            'title': ['h3', 'h2', 'h1'],
            'content': ['.PagePromo-content', 'p'],
            'link': 'a'
        },
        'cnn.com': {
            'container': '.container__item',
            'title': ['.container__headline', 'h3'],
            'content': ['.container__summary', 'p'],
            'link': 'a'
        },
        'bbc.com': {
            'container': '[data-testid="liverpool-card"]',
            'title': ['h3', 'h2'],
            'content': ['p', '.gs-c-promo-summary'],
            'link': 'a'
        },
        'reuters.com': {
            'container': '.story-card',
            'title': ['.story-title', 'h3'],
            'content': ['.story-excerpt', 'p'],
            'link': 'a'
        },
        'wsj.com': {
            'container': '.WSJTheme--headline',
            'title': ['h3', 'h2'],
            'content': ['.WSJTheme--summary', 'p'],
            'link': 'a'
        },
        'cnbc.com': {
            'container': 'a[href*="cnbc.com/202"], [data-module*="LatestNews"] a, .trending-item, [class*="Card"]:has(a[href*="/202"])',
            'title': ['span', 'h3', 'h2', '.Card-title'],
            'content': ['span', 'p'],
            'link': 'a'
        },
        'bing.com': {
            'container': '.news-card, .news-item, .newsitem, article[data-module="NewsCardCompact"], .caption, [class*="news"]',
            'title': ['.title', '.caption .title', 'h3', 'h4', 'a[aria-label]', '[aria-label]'],
            'content': ['.snippet', '.description', '.excerpt', 'p'],
            'link': 'a'
        }
    }
    
    for domain, config in site_configs.items():
        if domain in url.lower():
            return config
    return None


def _scrape_with_browser(source):
    """Headless scraping using Playwright to collect headlines with limited infinite scroll."""
    # Playwright is mandatory; no env-based disable

    # Ensure variables exist even if early errors occur
    candidate_articles = []
    created_count = 0
    analysis_post_ids = []

    try:
        from urllib.parse import urljoin

        logger.info(f"Playwright scraping from {source.url}")

        # Special handling for Twitter/X profiles so periodic scraping covers them
        try:
            url_lower = (source.url or "").lower()
            if "x.com/" in url_lower or "twitter.com/" in url_lower:
                session = None
                try:
                    session = TwitterSession.objects.order_by('-updated_at').first()
                except Exception:
                    session = None
                storage_state = session.storage_state if session and getattr(session, 'storage_state', None) else None
                tweets = scrape_twitter_profile(source.url, storage_state=storage_state, max_age_hours=None, backfill=True)
                created_count = 0
                analysis_post_ids = []
                for content, tweet_url, ts in tweets:
                    try:
                        if Post.objects.filter(url=tweet_url).exists():
                            continue
                        post = Post.objects.create(source=source, content=content, url=tweet_url, published_at=ts)
                        created_count += 1
                        analysis_post_ids.append(post.id)
                        send_dashboard_update(
                            "new_post",
                            {
                                "source": source.name,
                                "content_preview": content[:100] + ("..." if len(content) > 100 else ""),
                                "url": tweet_url,
                                "post_id": post.id,
                            },
                        )
                    except Exception:
                        continue
                for pid in analysis_post_ids:
                    try:
                        analyze_post.delay(pid)
                        send_dashboard_update(
                            "analysis_status",
                            {"post_id": pid, "status": "Queued (new post)"}
                        )
                    except Exception:
                        pass
                send_dashboard_update(
                    "scraper_status",
                    {"status": f"Twitter scrape created {created_count} posts", "source": source.name},
                )
                return
        except Exception as e:
            logger.warning(f"Twitter scraping fast-path failed; falling back to generic: {e}")

        site_config = _get_site_specific_selectors(source.url) or {}
        headline_selectors = [
            "h1 a", "h2 a", "h3 a",
            "h1", "h2", "h3",
            "a[aria-label]", "a[role='link'][href]",
            "[class*='headline'] a", "[class*='headline']",
            "[data-testid*='headline'] a", "[data-testid*='headline']",
        ]

        max_scrolls = 5
        min_title_len = 5

        # Use managed browser pool for efficient Chrome process management
        with get_managed_browser_page() as page:
            # Set shorter timeouts to prevent hanging
            page.set_default_timeout(15000)
            page.goto(source.url, wait_until="domcontentloaded", timeout=20000)

            try:
                page.wait_for_selector("body", timeout=10000)
            except Exception:
                pass

            last_height = 0
            for _ in range(max_scrolls):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                page.wait_for_timeout(1500)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height <= last_height:
                    break
                last_height = new_height

            elements = []
            container_selector = site_config.get("container")
            if container_selector:
                elements = page.query_selector_all(container_selector)
            if not elements:
                for sel in headline_selectors:
                    found = page.query_selector_all(sel)
                    if found:
                        elements.extend(found)

            # Collect candidate articles in Playwright context (no DB operations)
            seen_links = set()

            for el in elements:
                try:
                    title = (el.inner_text() or "").strip()
                    href = el.get_attribute("href")
                    anchor = None
                    if not href:
                        anchor = el.query_selector("a[href]")
                        href = anchor.get_attribute("href") if anchor else None
                    if not title and anchor:
                        title = (anchor.inner_text() or "").strip()

                    if not title or len(title) < min_title_len or not href:
                        continue

                    if href.startswith("/"):
                        href = urljoin(source.url, href)
                    if not _looks_like_article_url(href):
                        continue
                    if href in seen_links:
                        continue
                    seen_links.add(href)

                    # Store candidate without DB operations
                    candidate_articles.append({"title": title, "url": href})

                except Exception:
                    continue

        # Process candidates outside Playwright context using threading for async compatibility
        logger.info(f"Playwright found {len(candidate_articles)} candidate articles for {source.name}")
        created_count = 0
        logger.info(f"Processing {len(candidate_articles)} candidates for {source.name}")
        
        # Always use threading to ensure synchronous database context
        # This prevents async context issues in Celery workers
        import threading
        import queue
        
        def process_candidates_sync():
            """Process candidates in guaranteed synchronous context."""
            # Force new database connection in thread
            from django.db import connection
            connection.ensure_connection()
            
            sync_created_count = 0
            analysis_post_ids = []
            
            for i, candidate in enumerate(candidate_articles):
                try:
                    title = candidate["title"]
                    href = candidate["url"]

                    if Post.objects.filter(url=href).exists():
                        continue
                    if _is_duplicate_content(title, source):
                        continue

                    try:
                        post = Post.objects.create(source=source, content=title, url=href)
                    except Exception as db_err:
                        try:
                            # Refresh or recreate the Source if missing to survive FK races
                            try:
                                source_refreshed = Source.objects.get(pk=source.pk)
                            except Source.DoesNotExist:
                                source_refreshed, _ = Source.objects.get_or_create(
                                    url=source.url,
                                    defaults={
                                        "name": source.name,
                                        "scraping_enabled": True,
                                    },
                                )
                            post = Post.objects.create(source=source_refreshed, content=title, url=href)
                        except Exception as inner_err:
                            logger.error(
                                f"DB error creating post for {getattr(source,'name','<unknown>')}: {db_err}; retry failed: {inner_err}"
                            )
                            continue

                    sync_created_count += 1
                    analysis_post_ids.append(post.id)
                    
                    send_dashboard_update(
                        "new_post",
                        {
                            "source": source.name,
                            "content_preview": title[:100] + "...",
                            "url": href,
                            "post_id": post.id,
                        },
                    )
                    logger.debug(f"Created post {post.id}: {title[:50]}...")
                    
                except Exception as e:
                    logger.error(f"Error processing candidate {i}: {e}")
                    continue
                    
            return sync_created_count, analysis_post_ids
        
        # Always use threading to guarantee sync context
        logger.info("Using threading for database operations to ensure sync context")
        result_queue = queue.Queue()
        
        def thread_target():
            try:
                created_count, post_ids = process_candidates_sync()
                result_queue.put(("success", created_count, post_ids))
            except Exception as thread_err:
                logger.error(f"Threading error: {thread_err}")
                result_queue.put(("error", str(thread_err), []))
        
        thread = threading.Thread(target=thread_target)
        thread.start()
        thread.join(timeout=120)  # 2 minute timeout
        
        if thread.is_alive():
            logger.error("Threading operation timed out")
            created_count = 0
            analysis_post_ids = []
        else:
            try:
                status, created_count, analysis_post_ids = result_queue.get_nowait()
                if status != "success":
                    logger.error(f"Threading operation failed: {created_count}")
                    created_count = 0
                    analysis_post_ids = []
            except queue.Empty:
                logger.error("No result from threading operation")
                created_count = 0
                analysis_post_ids = []

        # Queue analysis tasks for successfully created posts
        for post_id in analysis_post_ids:
            try:
                analyze_post.delay(post_id)
                logger.debug(f"Queued analysis for post {post_id}")
                send_dashboard_update(
                    "analysis_status",
                    {"post_id": post_id, "status": "Queued (new post)"}
                )
            except Exception as e:
                logger.error(f"Failed to queue analysis for post {post_id}: {e}")

        logger.info(f"Playwright scraping completed for {source.name}: {created_count} headlines")

        if created_count == 0:
            send_dashboard_update(
                "scraper_status",
                {"status": f"No headlines found for {source.name}", "source": source.name},
            )

    except Exception as e:
        logger.error(f"Error in Playwright scraping {source.url}: {e}")
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "browser"}
        )


def _scrape_with_http(source) -> int:
    """Deprecated: HTTP fallback is disabled to enforce Playwright-only scraping."""
    logger.info("HTTP fallback disabled; Playwright-only mode")
    return 0


def _determine_scraping_method(source):
    """Determine whether to use RSS parsing or browser scraping based on URL"""
    url = source.url.lower()
    
    # RSS feed indicators
    rss_indicators = [
        'rss', 'feed', 'feeds/', '/rss/', '.rss', '.xml',
        'feeds.reuters.com', 'feeds.marketwatch.com', 'feeds.bloomberg.com',
        'feeds.finance.yahoo.com'
    ]
    
    # Check if it's likely an RSS feed
    if any(indicator in url for indicator in rss_indicators):
        return 'rss'
    
    # Default to browser scraping for dynamic content
    return 'browser'


def _scrape_api_source(source):
    """Scrape data from API endpoints like Reddit JSON API"""
    import requests
    import json
    from datetime import datetime, timedelta
    
    try:
        logger.info(f"API scraping from {source.api_endpoint or source.url}")
        
        # Prepare request
        url = source.api_endpoint or source.url
        headers = {
            'User-Agent': 'NewsTrader/1.0 (by /u/NewsTrader)'
        }
        
        # Add API key if configured
        if source.api_key_field:
            api_key = os.environ.get(source.api_key_field)
            if api_key:
                if source.api_key_field == 'REDDIT_USER_AGENT':
                    headers['User-Agent'] = api_key
                else:
                    headers['Authorization'] = f'Bearer {api_key}'
        
        # Prepare request parameters
        params = source.request_params or {}
        
        # Make request
        if source.request_type == 'POST':
            response = requests.post(url, headers=headers, json=params, timeout=30)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        
        response.raise_for_status()
        data = response.json()
        
        # Extract posts using data extraction config
        config = source.data_extraction_config or {}
        response_path = config.get('response_path', '')
        content_field = config.get('content_field', 'title')
        url_field = config.get('url_field', 'url')
        score_field = config.get('score_field', 'score')
        min_score = config.get('min_score', 0)
        published_field = config.get('published_field')
        
        # Navigate to the data using response_path
        current_data = data
        if response_path:
            for path_part in response_path.split('.'):
                if path_part and path_part in current_data:
                    current_data = current_data[path_part]
                else:
                    logger.warning(f"Path '{response_path}' not found in API response")
                    return
        
        if not isinstance(current_data, list):
            logger.warning(f"Expected list at path '{response_path}', got {type(current_data)}")
            return
        
        new_posts_count = 0
        cutoff_time = datetime.now() - timedelta(hours=_get_recent_hours_default())
        
        for item in current_data:  # Process all API items
            try:
                # Extract fields using dot notation
                title = _get_nested_value(item, content_field)
                url = _get_nested_value(item, url_field)
                score = _get_nested_value(item, score_field, 0)
                # Optional published timestamp filtering
                if published_field:
                    published_raw = _get_nested_value(item, published_field)
                    if published_raw:
                        try:
                            from dateutil import parser as dtparser
                            published_dt = dtparser.parse(published_raw)
                            if published_dt.tzinfo is None:
                                from datetime import timezone as dt_tz
                                published_dt = published_dt.replace(tzinfo=dt_tz.utc)
                            # Compare using naive now for simplicity
                            if published_dt.replace(tzinfo=None) < cutoff_time:
                                continue
                        except Exception:
                            pass
                
                if not title or not url:
                    continue
                
                # Check minimum score threshold
                if score < min_score:
                    continue
                
                # Ensure URL is absolute
                if url.startswith('/'):
                    url = 'https://reddit.com' + url
                elif not url.startswith('http'):
                    continue
                
                # Check if post already exists by URL or content similarity
                url_exists = Post.objects.filter(url=url).exists()
                content_duplicate = _is_duplicate_content(title, source)
                
                if url_exists:
                    logger.debug(f"Skipping API post - URL already exists: {url}")
                    continue
                elif content_duplicate:
                    logger.debug(f"Skipping API post - similar content: {title[:50]}...")
                    continue
                
                # Create new post
                try:
                    post = Post.objects.create(
                        source=source,
                        content=title,  # For Reddit, title is the content
                        url=url
                    )
                except Exception as db_err:
                    try:
                        source = Source.objects.get(pk=source.pk)
                        post = Post.objects.create(
                            source=source,
                            content=title,
                            url=url
                        )
                    except Exception:
                        logger.error(f"DB error creating API post for {source.name}: {db_err}")
                        return
                
                new_posts_count += 1
                logger.info(f"Created post: {title[:50]}... (Score: {score})")
                
                # Trigger analysis
                analyze_post.delay(post.id)
                
            except Exception as e:
                logger.error(f"Error processing API item: {e}")
                continue
        
        # Update source status
        from django.utils import timezone
        source.last_scraped_at = timezone.now()
        source.error_count = 0
        source.last_error = None
        source.scraping_status = "idle"
        source.save()
        
        logger.info(f"API scraping completed for {source.name}. Created {new_posts_count} new posts.")
        
        if new_posts_count == 0:
            logger.warning(f"No new posts found from {source.name} - check API response format or score threshold")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for {source.name}: {e}")
        source.error_count += 1
        source.last_error = f"API request failed: {str(e)}"
        source.scraping_status = "error"
        source.save()
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response from {source.name}: {e}")
        source.error_count += 1
        source.last_error = f"Invalid JSON response: {str(e)}"
        source.scraping_status = "error"
        source.save()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in API scraping for {source.name}: {e}")
        source.error_count += 1
        source.last_error = f"Unexpected error: {str(e)}"
        source.scraping_status = "error"
        source.save()
        raise


def _get_nested_value(data, path, default=None):
    """Get value from nested dict using dot notation (e.g., 'data.title')"""
    current = data
    for key in path.split('.'):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def _scrape_source(source):
    """Main scraping function that routes to appropriate method"""
    
    # Check if source has RSS feed configuration from auto-detection
    extraction_config = getattr(source, 'data_extraction_config', None) or {}
    if extraction_config.get('rss_feed') and extraction_config.get('feed_url'):
        logger.info(f"Using RSS feed from auto-detection: {extraction_config['feed_url']}")
        # Temporarily override the URL for RSS scraping
        original_url = source.url
        source.url = extraction_config['feed_url']
        try:
            _scrape_rss_feed(source)
        finally:
            source.url = original_url  # Always restore original URL
        return
    
    # Check if source is configured for API scraping
    if source.scraping_method == 'api':
        _scrape_api_source(source)
    elif source.scraping_method == 'both':
        # Try API first, fallback to other methods
        try:
            _scrape_api_source(source)
        except Exception as e:
            logger.warning(f"API scraping failed for {source.name}, falling back to other method: {e}")
            scraping_method = _determine_scraping_method(source)
            if scraping_method == 'rss':
                _scrape_rss_feed(source)
            else:
                _scrape_with_browser(source)
    else:
        # Use the existing method determination
        scraping_method = _determine_scraping_method(source)
        logger.info(f"Scraping {source.name} using method: {scraping_method}")
        
        if scraping_method == 'rss':
            _scrape_rss_feed(source)
        else:
            _scrape_with_browser(source)


def get_active_trading_config():
    """Get the active trading configuration or create a default one."""
    def _query():
        try:
            cfg = TradingConfig.objects.filter(is_active=True).first()
            if cfg:
                return cfg
        except TradingConfig.DoesNotExist:
            pass
        # Create default config if none exists
        return TradingConfig.objects.create(
            name="Default Configuration", is_active=True
        )

    if _is_async_context():
        return _run_db_call_in_thread(_query)
    return _query()


def is_trading_allowed():
    """Check if trading is currently allowed based on configuration."""
    config = get_active_trading_config()
    if not config or not config.trading_enabled:
        return False, "Trading is disabled in configuration"

    # Market-hours-only constraint removed per requirements

    return True, "Trading allowed"


def check_daily_trade_limit():
    """Check if daily trade limit has been reached."""
    config = get_active_trading_config()
    if not config:
        return True, "No configuration found"

    today = timezone.now().date()
    today_trades = Trade.objects.filter(
        created_at__date=today, status__in=["open", "closed"]
    ).count()

    if today_trades >= config.max_daily_trades:
        return (
            False,
            f"Daily trade limit reached ({today_trades}/{config.max_daily_trades})",
        )

    return True, f"Trade limit OK ({today_trades}/{config.max_daily_trades})"


@shared_task
def scrape_posts(source_id=None, manual_test=False):
    """Scrape posts from all configured sources or a specific source."""
    logger.info(f"Scrape posts task initiated. Source ID: {source_id}, Manual test: {manual_test}")

    # Check if bot is enabled (skip check for manual tests)
    if not manual_test:
        trading_config = get_active_trading_config()
        if trading_config and not trading_config.bot_enabled:
            logger.info("Bot is disabled. Skipping automated scraping task.")
            return
    else:
        logger.info("Manual test scraping - bypassing bot enabled check.")

    # Always resolve sources fresh from DB; avoid stale IDs after deletes
    def _resolve_sources():
        if source_id:
            try:
                qs = Source.objects.filter(id=source_id)
                if not qs.exists():
                    logger.warning(f"Source with ID {source_id} not found; attempting fallback by name/url")
                    qs = Source.objects.all()
                    if not qs.exists():
                        send_dashboard_update(
                            "scraper_error",
                            {"source": "N/A", "error": f"No sources available to scrape (requested ID {source_id})"},
                        )
                        return None
                return qs
            except Exception as e:
                logger.error(f"Error resolving source {source_id}: {e}")
                send_dashboard_update(
                    "scraper_error",
                    {"source": "N/A", "error": f"Error resolving source {source_id}: {e}"},
                )
                return None
        else:
            return Source.objects.all()

    sources = _run_db_call_in_thread(_resolve_sources) if _is_async_context() else _resolve_sources()
    if sources is None:
        return

    # Only process enabled sources (RSS feeds, browser scraping, and API)
    active_sources = (_run_db_call_in_thread(lambda: sources.filter(scraping_enabled=True))
                      if _is_async_context() else sources.filter(scraping_enabled=True))
    
    # Send start message with source names
    if (_run_db_call_in_thread(active_sources.exists) if _is_async_context() else active_sources.exists()):
        source_names = [source.name for source in active_sources]
        if len(source_names) == 1:
            send_dashboard_update(
                "scraper_status",
                {"status": f"Started scraping {source_names[0]}", "source": source_names[0]},
            )
        else:
            send_dashboard_update(
                "scraper_status", 
                {"status": f"Started scraping {len(source_names)} sources", "sources": source_names},
            )
    
    scraped_sources = []
    for source in active_sources:
        try:
            logger.info(f"Starting to scrape: {source.name}")
            _scrape_source(source)
            scraped_sources.append(source.name)
            send_dashboard_update(
                "scraper_status",
                {"status": f"Completed scraping {source.name}", "source": source.name},
            )
        except Exception as e:
            logger.error(f"Error scraping source {source.name}: {e}")
            send_dashboard_update(
                "scraper_error",
                {"source": source.name, "error": str(e), "method": "scraping"},
            )
    
    # Log disabled sources being skipped (make DB-safe in async contexts)
    if _is_async_context():
        disabled_sources = _run_db_call_in_thread(lambda: list(sources.filter(scraping_enabled=False)))
    else:
        disabled_sources = list(sources.filter(scraping_enabled=False))

    for source in disabled_sources:
        logger.info(f"Skipping disabled source: {source.name}")

    # Send final status with results
    if scraped_sources:
        if len(scraped_sources) == 1:
            send_dashboard_update(
                "scraper_status", 
                {"status": f"Scraping finished: {scraped_sources[0]}", "source": scraped_sources[0]}
            )
        else:
            send_dashboard_update(
                "scraper_status", 
                {"status": f"Scraping finished: {len(scraped_sources)} sources completed", "sources": scraped_sources}
            )
    else:
        send_dashboard_update("scraper_status", {"status": "Scraping finished: No sources processed"})
    
    logger.info(f"Scraping finished. Processed: {', '.join(scraped_sources) if scraped_sources else 'None'}")


@shared_task
def analyze_post(post_id, manual_test=False):
    """Analyze a post with an LLM."""
    logger.info(f"Analyzing post {post_id} with LLM (manual_test={manual_test}).")

    # Check if bot is enabled (unless this is a manual test)
    if not manual_test:
        trading_config = get_active_trading_config()
        if trading_config and not trading_config.bot_enabled:
            logger.info("Bot is disabled. Skipping analysis task.")
            return

    post = Post.objects.get(id=post_id)
    
    # Skip if already analyzed
    if hasattr(post, "analysis"):
        logger.info(f"Post {post.id} already has analysis. Skipping LLM call.")
        send_dashboard_update(
            "analysis_skipped",
            {
                "post_id": post.id,
                "reason": "Post already analyzed",
                "post_type": "existing",
            },
        )
        return

    # Validate: Skip analysis for simulated/error posts
    if _is_simulated_post(post):
        logger.info(f"Skipping LLM analysis for simulated post {post.id}: {post.url}")
        send_dashboard_update(
            "analysis_skipped", 
            {
                "post_id": post.id, 
                "reason": "Simulated post - no LLM analysis needed",
                "post_type": "simulated"
            }
        )
        return
    
    send_dashboard_update(
        "analysis_status", {"post_id": post.id, "status": "Analysis started"}
    )

    # Get active trading configuration
    config = get_active_trading_config()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error(
            "OPENAI_API_KEY not found in environment variables. Cannot analyze post."
        )
        send_dashboard_update(
            "analysis_error",
            {"post_id": post.id, "error": "OPENAI_API_KEY not configured"},
        )
        return

    llm_output = {}
    raw_response_content = None
    trade_executed_flag = False

    try:
        # Use configurable LLM model and prompt
        model = config.llm_model if config else "gpt-3.5-turbo"
        prompt = (
            config.llm_prompt_template
            if config
            else """You are a financial analyst. Analyze the given text for potential financial impact on a stock. 
Respond with a JSON object: { "symbol": "STOCK_SYMBOL", "direction": "buy", "confidence": 0.87, "reason": "Explanation" }. 
Direction can be 'buy', 'sell', or 'hold'. Confidence is a float between 0 and 1."""
        )

        # Create OpenAI client with API key passed directly
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": (
                    "You are given ONLY a news headline. Do not assume details beyond the headline.\n"
                    "Headline:" + "\n\n" + post.content
                )},
            ],
            response_format={"type": "json_object"},
            temperature=getattr(config, "llm_temperature", 0.1) if config else 0.1,
            max_tokens=getattr(config, "llm_max_tokens", 1000) if config else 1000,
        )

        raw_response_content = response.choices[0].message.content
        llm_output = json.loads(raw_response_content)

        analysis = Analysis.objects.create(
            post=post,
            symbol=llm_output.get("symbol", "UNKNOWN"),
            direction=llm_output.get("direction", "hold"),
            confidence=llm_output.get("confidence", 0.0),
            reason=llm_output.get("reason", "No reason provided by LLM."),
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        logger.info(
            f"Analysis complete for post {post.id}: Symbol={analysis.symbol}, Direction={analysis.direction}, Confidence={analysis.confidence}"
        )

        # Check if trade should be executed based on configuration
        confidence_threshold = config.min_confidence_threshold if config else 0.7
        if (
            analysis.direction in ["buy", "sell"]
            and analysis.confidence >= confidence_threshold
        ):
            # Check trading limits
            trading_allowed, reason = is_trading_allowed()
            daily_limit_ok, daily_reason = check_daily_trade_limit()

            if trading_allowed and daily_limit_ok:
                trade_executed_flag = True
                execute_trade.delay(analysis.id)
            else:
                logger.info(
                    f"Trade not executed for analysis {analysis.id}: Trading={reason}, Daily={daily_reason}"
                )
                send_dashboard_update(
                    "trade_skipped",
                    {
                        "analysis_id": analysis.id,
                        "reason": f"Trading: {reason}, Daily: {daily_reason}",
                    },
                )
                # If daily limit is reached, raise alert via dashboard update
                if not daily_limit_ok:
                    send_dashboard_update(
                        "trade_rejected",
                        {
                            "analysis_id": analysis.id,
                            "symbol": analysis.symbol,
                            "reason": "Daily trade limit reached",
                            "tag": "Limit",
                        },
                    )

        send_dashboard_update(
            "new_analysis",
            {
                "post_id": post.id,
                "symbol": analysis.symbol,
                "direction": analysis.direction,
                "confidence": analysis.confidence,
                "reason": analysis.reason[:100] + "...",
                "trade_executed": trade_executed_flag,
            },
        )

    except json.JSONDecodeError as e:
        error_msg = f"LLM response for post {post.id} was not valid JSON: {e}. Raw response: {raw_response_content}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM returned invalid JSON: {e}",
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        send_dashboard_update(
            "analysis_error", {"post_id": post.id, "error": error_msg}
        )
    except Exception as e:
        error_msg = f"Error analyzing post {post.id} with LLM: {e}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM analysis failed: {e}",
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        send_dashboard_update(
            "analysis_error", {"post_id": post.id, "error": error_msg}
        )


@shared_task
def execute_trade(analysis_id):
    """Execute a trade based on an analysis with enhanced position management."""
    logger.info(f"Processing trade analysis {analysis_id}.")

    # Check if bot is enabled
    trading_config = get_active_trading_config()
    if trading_config and not trading_config.bot_enabled:
        logger.info("Bot is disabled. Skipping trade execution.")
        return

    if _is_async_context():
        analysis = _run_db_call_in_thread(lambda: Analysis.objects.get(id=analysis_id))
    else:
        analysis = Analysis.objects.get(id=analysis_id)
    send_dashboard_update(
        "trade_status",
        {"analysis_id": analysis.id, "status": "Analyzing position management"},
    )

    # Check for existing active position for the same tracked company/symbol
    def _find_existing():
        from .models import TrackedCompany
        tc = TrackedCompany.objects.filter(symbol__iexact=analysis.symbol).first()
        if tc:
            return Trade.objects.filter(tracked_company=tc, status__in=["open", "pending", "pending_close"]).first()
        return Trade.objects.filter(symbol=analysis.symbol, status__in=["open", "pending", "pending_close"]).first()
    existing_trade = _run_db_call_in_thread(_find_existing) if _is_async_context() else _find_existing()

    if existing_trade:
        logger.info(f"Found existing open position for {analysis.symbol}: {existing_trade.direction}")
        
        if analysis.direction != existing_trade.direction:
            # Conflicting direction → Close position (market consensus lost)
            logger.info(f"Conflicting analysis for {analysis.symbol}: existing {existing_trade.direction}, new {analysis.direction}. Closing position.")
            close_trade_due_to_conflict.delay(existing_trade.id, analysis.id)
        else:
            # Supporting direction → Adjust TP/SL if conditions are met
            logger.info(f"Supporting analysis for {analysis.symbol}: {analysis.direction}. Checking for adjustment.")
            adjust_position_risk.delay(existing_trade.id, analysis.id)
    else:
        # No existing position → Create new trade
        logger.info(f"No existing position for {analysis.symbol}. Creating new trade.")
        create_new_trade.delay(analysis.id)


def get_effective_concurrent_open_trades_count():
    """Return effective count of open trades based on Alpaca plus pending DB trades.

    Logic:
    - Count current open positions from Alpaca (unique symbols)
    - Add DB trades in pending/pending_close whose symbols are not already open at Alpaca
    This ensures the limit reflects actual broker state plus in-flight orders.
    """
    positions_symbols = set()
    try:
        ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
        ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
        ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if ALPACA_API_KEY and ALPACA_SECRET_KEY:
            try:
                import alpaca_trade_api as tradeapi  # Lazy import to avoid test/runtime coupling
                api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)
                try:
                    positions = api.list_positions()
                    positions_symbols = {getattr(p, "symbol", None) or p.symbol for p in positions}
                except Exception:
                    positions_symbols = set()
            except Exception:
                # If import or API fails, fall back to DB-only pending consideration below
                positions_symbols = set()
    except Exception:
        positions_symbols = set()

    # DB pending/pending_close trades which may not yet be visible as positions at Alpaca
    try:
        pending_symbols = set(
            Trade.objects.filter(status__in=["pending", "pending_close"]).values_list("symbol", flat=True)
        )
    except Exception:
        pending_symbols = set()

    additional_pending = len([s for s in pending_symbols if s not in positions_symbols])
    return len(positions_symbols) + additional_pending


def get_effective_open_exposure():
    """Return current total open exposure based on Alpaca positions plus DB pending trades not yet open.

    - From Alpaca: sum absolute market_value for each position (fallback to qty * avg_entry_price)
    - From DB: add pending/pending_close trades whose symbols are not currently open at Alpaca, using entry_price * quantity when available
    """
    positions_symbols = set()
    total_exposure = 0.0

    try:
        ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
        ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
        ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if ALPACA_API_KEY and ALPACA_SECRET_KEY:
            try:
                import alpaca_trade_api as tradeapi
                api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)
                positions = []
                try:
                    positions = api.list_positions()
                except Exception:
                    positions = []

                for pos in positions:
                    try:
                        symbol = getattr(pos, "symbol", None) or pos.symbol
                        positions_symbols.add(symbol)
                        market_value = getattr(pos, "market_value", None)
                        if market_value is not None:
                            total_exposure += abs(float(market_value))
                        else:
                            qty = float(getattr(pos, "qty", 0) or 0)
                            avg_entry_price = float(getattr(pos, "avg_entry_price", 0) or 0)
                            total_exposure += abs(qty * avg_entry_price)
                    except Exception:
                        # Skip malformed position entry
                        continue
            except Exception:
                # Fall through to DB-only fallback below
                positions_symbols = set()
    except Exception:
        positions_symbols = set()

    # Include DB pending exposures for symbols not yet open at Alpaca
    try:
        pending_trades = Trade.objects.filter(status__in=["pending", "pending_close"])  # type: ignore
        for t in pending_trades:
            try:
                if t.symbol not in positions_symbols and t.entry_price and t.quantity:
                    total_exposure += abs(float(t.entry_price) * float(t.quantity))
            except Exception:
                continue
    except Exception:
        pass

    return total_exposure

@shared_task
def create_new_trade(analysis_id):
    """Create a new trade for the given analysis."""
    analysis = _run_db_call_in_thread(lambda: Analysis.objects.get(id=analysis_id)) if _is_async_context() else Analysis.objects.get(id=analysis_id)
    config = get_active_trading_config()

    logger.info(f"Creating new trade for analysis {analysis_id}: {analysis.symbol} {analysis.direction}")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not found in environment variables. Cannot execute trade.")
        send_dashboard_update(
            "trade_error",
            {"analysis_id": analysis.id, "error": "Alpaca API keys not configured"},
        )
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

    try:
        # Enforce configurable limits (concurrent trades and total exposure)
        if config:
            # Count open positions (from Alpaca) plus DB pending/pending_close not yet open
            concurrent_count = get_effective_concurrent_open_trades_count()
            if config.max_concurrent_open_trades and concurrent_count >= config.max_concurrent_open_trades:
                logger.warning(
                    f"Rejected new trade due to concurrent open trades limit: {concurrent_count}/{config.max_concurrent_open_trades}"
                )
                send_dashboard_update(
                    "trade_rejected",
                    {
                        "analysis_id": analysis.id,
                        "symbol": analysis.symbol,
                        "reason": "Concurrent trades limit reached",
                        "limit": config.max_concurrent_open_trades,
                        "tag": "Rejected",
                    },
                )
                return

        # Determine position size
        position_size = config.default_position_size if config else 100.0

        # Get current stock price for quantity calculation
        try:
            ticker = api.get_latest_trade(analysis.symbol)
            current_price = ticker.price
            quantity = int(position_size / current_price)
            if quantity < 1:
                quantity = 1
        except Exception as e:
            logger.warning(
                f"Could not get current price for {analysis.symbol}: {e}. Using quantity 1."
            )
            quantity = 1
            current_price = 0.0

        # Check exposure against configured max_total_open_exposure
        if config and config.max_total_open_exposure:
            current_exposure = get_effective_open_exposure()
            projected_exposure = current_exposure + float(position_size)
            if projected_exposure > float(config.max_total_open_exposure):
                logger.warning(
                    f"Rejected new trade due to exposure limit: projected {projected_exposure:.2f} > max {config.max_total_open_exposure:.2f}"
                )
                send_dashboard_update(
                    "trade_rejected",
                    {
                        "analysis_id": analysis.id,
                        "symbol": analysis.symbol,
                        "reason": "Total exposure limit reached",
                        "current_exposure": current_exposure,
                        "projected_exposure": projected_exposure,
                        "max_exposure": config.max_total_open_exposure,
                        "tag": "Rejected",
                    },
                )
                return

        # Enforce tracked-company requirement for analysis-driven trades
        try:
            from .models import TrackedCompany
            tc_enforced = TrackedCompany.objects.filter(symbol__iexact=analysis.symbol).first()
        except Exception:
            tc_enforced = None
        if not tc_enforced:
            logger.warning(f"Rejected new trade for untracked symbol: {analysis.symbol}")
            send_dashboard_update(
                "trade_rejected",
                {
                    "analysis_id": analysis.id,
                    "symbol": analysis.symbol,
                    "reason": "Symbol not in tracked companies",
                    "tag": "Rejected",
                },
            )
            return

        # Submit order to Alpaca (market order). Broker-side TP/SL intentionally not used per requirements
        order = api.submit_order(
            symbol=analysis.symbol,
            qty=quantity,
            side=analysis.direction,  # "buy" or "sell"
            type="market",
            time_in_force="gtc",
        )

        # Calculate stop loss and take profit prices
        stop_loss_price = None
        take_profit_price = None
        if config and current_price > 0:
            if analysis.direction == "buy":
                stop_loss_price = current_price * (1 - config.stop_loss_percentage / 100)
                take_profit_price = current_price * (1 + config.take_profit_percentage / 100)
            else:  # sell
                stop_loss_price = current_price * (1 + config.stop_loss_percentage / 100)
                take_profit_price = current_price * (1 - config.take_profit_percentage / 100)

        # Create trade record, resilient to race duplicates (unique_active_trade_per_symbol)
        def _create_trade():
            from django.db import IntegrityError
            try:
                # Resolve tracked company by symbol for FK
                from .models import TrackedCompany
                tc = None
                try:
                    tc = TrackedCompany.objects.filter(symbol__iexact=analysis.symbol).first()
                except Exception:
                    tc = None
                return Trade.objects.create(
                    analysis=analysis,
                    symbol=analysis.symbol,
                    tracked_company=tc,
                    direction=analysis.direction,
                    quantity=quantity,
                    entry_price=current_price,
                    status="pending",
                    alpaca_order_id=order.id,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    original_stop_loss_price=stop_loss_price,
                    original_take_profit_price=take_profit_price,
                    take_profit_price_percentage=10.0 if config is None else (config.take_profit_percentage or 10.0),
                    stop_loss_price_percentage=2.0 if config is None else (config.stop_loss_percentage or 2.0),
                )
            except IntegrityError:
                # Another worker created the active trade concurrently; return it instead
                return Trade.objects.filter(
                    tracked_company__symbol__iexact=analysis.symbol,
                    status__in=["open", "pending", "pending_close"],
                ).order_by("-created_at").first()
        trade = _run_db_call_in_thread(_create_trade) if _is_async_context() else _create_trade()

        logger.info(
            f"Submitted {analysis.direction.upper()} order for {analysis.symbol}. Trade ID: {trade.id}, Order ID: {order.id}"
        )

        send_dashboard_update(
            "new_trade",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "quantity": trade.quantity,
                "status": trade.status,
                "entry_price": trade.entry_price,
                "stop_loss_price": trade.stop_loss_price,
                "take_profit_price": trade.take_profit_price,
            },
        )

    except Exception as e:
        error_msg = f"Error creating new trade for analysis {analysis.id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"analysis_id": analysis.id, "error": error_msg}
        )


@shared_task
def adjust_position_risk(trade_id, analysis_id):
    """Adjust TP/SL for existing position based on supporting analysis."""
    trade = Trade.objects.get(id=trade_id)
    analysis = Analysis.objects.get(id=analysis_id)
    config = get_active_trading_config()

    logger.info(f"Evaluating position adjustment for trade {trade_id} based on analysis {analysis_id}")

    # Check if adjustments are allowed and not already done
    if not config or not config.allow_position_adjustments:
        logger.info(f"Position adjustments disabled in config for trade {trade_id}")
        return

    if trade.has_been_adjusted:
        logger.info(f"Trade {trade_id} has already been adjusted. Skipping.")
        return

    # Check confidence threshold
    if analysis.confidence < config.min_confidence_for_adjustment:
        logger.info(
            f"Analysis confidence {analysis.confidence} below adjustment threshold "
            f"{config.min_confidence_for_adjustment} for trade {trade_id}"
        )
        return

    try:
        # Calculate conservative adjustment based on analysis confidence
        adjustment_factor = analysis.confidence * config.conservative_adjustment_factor

        logger.info(
            f"Applying conservative adjustment (factor: {adjustment_factor:.2f}) to trade {trade_id}"
        )

        # Adjust take profit (move further out for supporting news)
        if trade.take_profit_price and trade.entry_price:
            current_tp_distance = abs(trade.take_profit_price - trade.entry_price)
            additional_distance = current_tp_distance * adjustment_factor * 0.1  # 10% max extension

            if trade.direction == "buy":
                new_tp = trade.take_profit_price + additional_distance
            else:  # sell
                new_tp = trade.take_profit_price - additional_distance

            trade.take_profit_price = new_tp
            logger.info(f"Adjusted TP for trade {trade_id}: {trade.take_profit_price:.2f}")

        # Adjust stop loss (tighten to lock in profits, but never loosen beyond current for trailing)
        if trade.stop_loss_price and trade.entry_price:
            current_sl_distance = abs(trade.stop_loss_price - trade.entry_price)
            tighter_distance = current_sl_distance * (1 - adjustment_factor * 0.3)  # Up to 30% tighter

            if trade.direction == "buy":
                proposed_sl = trade.entry_price - tighter_distance
                if trade.stop_loss_price is None or proposed_sl > float(trade.stop_loss_price):
                    trade.stop_loss_price = proposed_sl
            else:  # sell
                proposed_sl = trade.entry_price + tighter_distance
                if trade.stop_loss_price is None or proposed_sl < float(trade.stop_loss_price):
                    trade.stop_loss_price = proposed_sl
            logger.info(f"Adjusted SL for trade {trade_id}: {trade.stop_loss_price:.2f}")

        # Mark as adjusted (one-time only)
        trade.has_been_adjusted = True
        trade.save()

        send_dashboard_update(
            "position_adjusted",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "new_take_profit": trade.take_profit_price,
                "new_stop_loss": trade.stop_loss_price,
                "adjustment_factor": adjustment_factor,
                "analysis_confidence": analysis.confidence,
            },
        )

        logger.info(f"Successfully adjusted position for trade {trade_id}")

    except Exception as e:
        error_msg = f"Error adjusting position for trade {trade_id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"trade_id": trade_id, "error": error_msg}
        )


@shared_task
def close_trade_due_to_conflict(trade_id, conflicting_analysis_id):
    """Close a trade due to conflicting market analysis (no consensus)."""
    trade = Trade.objects.get(id=trade_id)
    analysis = Analysis.objects.get(id=conflicting_analysis_id)

    logger.info(
        f"Closing trade {trade_id} ({trade.symbol} {trade.direction}) due to conflicting analysis "
        f"{conflicting_analysis_id} ({analysis.direction})"
    )

    try:
        # Set close reason and status
        trade.status = "pending_close"
        trade.close_reason = "market_consensus_lost"
        trade.save()

        # Use existing manual close logic
        close_trade_manually.delay(trade_id)

        send_dashboard_update(
            "trade_closed_conflict",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "original_direction": trade.direction,
                "conflicting_direction": analysis.direction,
                "reason": "Market consensus lost",
            },
        )

        logger.info(f"Initiated close for conflicting trade {trade_id}")

    except Exception as e:
        error_msg = f"Error closing conflicting trade {trade_id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"trade_id": trade_id, "error": error_msg}
        )


@shared_task
def close_expired_positions():
    """Close positions that have exceeded the maximum hold time."""
    # Wrap DB access to avoid async context errors
    config = get_active_trading_config()
    if not config:
        logger.warning("No active trading config found. Skipping expired position cleanup.")
        return

    def _fetch_expired():
        cutoff_time = timezone.now() - timedelta(hours=config.max_position_hold_time_hours)
        qs = Trade.objects.filter(status__in=["open", "pending_close"], opened_at__lt=cutoff_time)
        return list(qs)

    expired_trades = _run_db_call_in_thread(_fetch_expired) if _is_async_context() else _fetch_expired()
    expired_count = len(expired_trades)
    if expired_count == 0:
        logger.info("No expired positions found.")
        return

    logger.info(f"Found {expired_count} expired positions to close (older than {config.max_position_hold_time_hours} hours)")

    closed_count = 0
    failed_count = 0

    for trade in expired_trades:
        try:
            # Set close reason and status, then initiate close
            trade.status = "pending_close"
            trade.close_reason = "time_limit"
            # Persist in a DB-safe way if needed
            if _is_async_context():
                _run_db_call_in_thread(lambda: trade.save())
            else:
                trade.save()

            close_trade_manually.delay(trade.id)
            closed_count += 1
            
            logger.info(f"Initiated time-based close for trade {trade.id} ({trade.symbol})")

        except Exception as e:
            failed_count += 1
            logger.error(f"Error closing expired trade {trade.id}: {e}")

    # Send dashboard update
    send_dashboard_update(
        "expired_positions_closed",
        {
            "total_expired": expired_count,
            "closed_count": closed_count,
            "failed_count": failed_count,
            "max_hold_hours": config.max_position_hold_time_hours,
        },
    )

    logger.info(f"Expired position cleanup completed: {closed_count} initiated, {failed_count} failed")


@shared_task
def monitor_local_stop_take_levels():
    """Monitor open positions for local TP/SL triggers without sending to Alpaca.

    If running in an async event loop thread, offload the DB work to a plain thread
    to avoid Django SynchronousOnlyOperation errors.
    """
    def _impl():
        config = get_active_trading_config()
        if not config:
            logger.warning("No active trading config found. Skipping TP/SL monitoring.")
            return

        # Get all open trades (including those pending close)
        open_trades = Trade.objects.filter(status__in=["open", "pending_close"])
        
        if not open_trades.exists():
            logger.debug("No open trades to monitor.")
            return

        logger.info(f"Monitoring {open_trades.count()} open positions for TP/SL triggers")

        ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
        ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
        ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
            logger.warning("Alpaca API keys not configured. Skipping TP/SL monitoring.")
            return

        api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

        triggered_count = 0

        for trade in open_trades:
            try:
                current_price = None
                try:
                    position = api.get_position(trade.symbol)
                    current_price = float(position.current_price)
                except Exception:
                    try:
                        ticker = api.get_latest_trade(trade.symbol)
                        current_price = float(ticker.price)
                    except Exception:
                        current_price = float(trade.entry_price or 0)

                try:
                    logger.info(
                        f"TP/SL check trade #{trade.id} {trade.symbol} dir={trade.direction} "
                        f"price={current_price:.4f} tp={trade.take_profit_price} sl={trade.stop_loss_price}"
                    )
                except Exception:
                    pass

                use_percent_based_tp = trade.take_profit_price_percentage is not None
                use_percent_based_sl = trade.stop_loss_price_percentage is not None

                pnl_percent = None
                if use_percent_based_tp or use_percent_based_sl:
                    try:
                        if trade.direction == "buy":
                            pnl_percent = (
                                (current_price - float(trade.entry_price)) / float(trade.entry_price)
                            ) * 100.0 if trade.entry_price else None
                        else:
                            pnl_percent = (
                                (float(trade.entry_price) - current_price) / float(trade.entry_price)
                            ) * 100.0 if trade.entry_price else None
                    except Exception:
                        pnl_percent = None

                # Trailing stop maintenance (before computing triggers)
                try:
                    config_ts_enabled = getattr(config, "trailing_stop_enabled", False)
                    if config_ts_enabled and current_price and trade.entry_price:
                        activation_pct = float(
                            getattr(config, "trailing_stop_activation_profit_percentage", 0.0)
                        )
                        distance_pct = float(
                            getattr(config, "trailing_stop_distance_percentage", 1.0)
                        )

                        # Compute current PnL %
                        pnl_pct_for_activation = None
                        try:
                            if trade.direction == "buy":
                                pnl_pct_for_activation = (
                                    (current_price - float(trade.entry_price)) / float(trade.entry_price)
                                ) * 100.0
                            else:
                                pnl_pct_for_activation = (
                                    (float(trade.entry_price) - current_price) / float(trade.entry_price)
                                ) * 100.0
                        except Exception:
                            pnl_pct_for_activation = None

                        # Update extremes
                        if trade.direction == "buy":
                            if trade.highest_price_since_open is None or current_price > float(trade.highest_price_since_open):
                                trade.highest_price_since_open = current_price
                        else:
                            if trade.lowest_price_since_open is None or current_price < float(trade.lowest_price_since_open):
                                trade.lowest_price_since_open = current_price

                        # If activated, compute trailing SL level from extremes
                        if pnl_pct_for_activation is not None and pnl_pct_for_activation >= activation_pct:
                            if trade.direction == "buy" and trade.highest_price_since_open:
                                new_trailing_sl = float(trade.highest_price_since_open) * (1 - distance_pct / 100.0)
                                # Only raise SL for longs
                                if trade.stop_loss_price is None or new_trailing_sl > float(trade.stop_loss_price):
                                    trade.stop_loss_price = new_trailing_sl
                            elif trade.direction == "sell" and trade.lowest_price_since_open:
                                new_trailing_sl = float(trade.lowest_price_since_open) * (1 + distance_pct / 100.0)
                                # Only lower SL for shorts
                                if trade.stop_loss_price is None or new_trailing_sl < float(trade.stop_loss_price):
                                    trade.stop_loss_price = new_trailing_sl

                        # Persist trailing references and potential SL update
                        try:
                            trade.save(update_fields=[
                                "highest_price_since_open",
                                "lowest_price_since_open",
                                "stop_loss_price",
                                "updated_at",
                            ])
                        except Exception:
                            pass
                except Exception as _ts_err:
                    logger.debug(f"Trailing stop maintenance skipped for trade {trade.id}: {_ts_err}")

                stop_triggered = False
                if use_percent_based_sl and pnl_percent is not None:
                    try:
                        sl_pct = float(trade.stop_loss_price_percentage)
                        if pnl_percent <= -sl_pct:
                            logger.info(
                                f"Stop loss % triggered for trade {trade.id} ({trade.symbol}): pnl%={pnl_percent:.2f} vs SL% {sl_pct}"
                            )
                            stop_triggered = True
                    except Exception:
                        stop_triggered = False
                # Always allow absolute price-based SL (including trailing) to trigger
                if not stop_triggered and should_trigger_stop_loss(trade, current_price):
                    stop_triggered = True

                if stop_triggered:
                    logger.info(f"Stop loss triggered for trade {trade.id} ({trade.symbol}): {current_price} vs SL {trade.stop_loss_price}")
                    trade.status = "pending_close"
                    trade.close_reason = "stop_loss"
                    trade.save()
                    close_trade_manually.delay(trade.id)
                    triggered_count += 1
                elif (
                    (use_percent_based_tp and pnl_percent is not None and 
                     pnl_percent >= float(trade.take_profit_price_percentage))
                    or should_trigger_take_profit(trade, current_price)
                ):
                    logger.info(f"Take profit triggered for trade {trade.id} ({trade.symbol}): {current_price} vs TP {trade.take_profit_price}")
                    trade.status = "pending_close"
                    trade.close_reason = "take_profit"
                    trade.save()
                    close_trade_manually.delay(trade.id)
                    triggered_count += 1
                else:
                    if not trade.take_profit_price and not trade.stop_loss_price:
                        logger.info(
                            f"No TP/SL set for trade #{trade.id} {trade.symbol}; skipping trigger checks"
                        )
            except Exception as e:
                logger.error(f"Error monitoring trade {trade.id} ({trade.symbol}): {e}")

        if triggered_count > 0:
            logger.info(f"TP/SL monitoring completed: {triggered_count} positions triggered")

    # If an asyncio event loop is running in this thread, offload to a clean thread
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if loop_running:
        import threading
        error_holder = {}
        def _runner():
            try:
                _impl()
            except Exception as e:
                error_holder['e'] = e
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        if 'e' in error_holder:
            raise error_holder['e']
        return
    else:
        return _impl()


def should_trigger_stop_loss(trade, current_price):
    """Check if stop loss should be triggered for a trade."""
    if not trade.stop_loss_price:
        return False

    if trade.direction == "buy":
        # For long positions, stop loss triggers when price falls below SL
        return current_price <= trade.stop_loss_price
    else:  # sell
        # For short positions, stop loss triggers when price rises above SL
        return current_price >= trade.stop_loss_price


def should_trigger_take_profit(trade, current_price):
    """Check if take profit should be triggered for a trade."""
    if not trade.take_profit_price:
        return False

    if trade.direction == "buy":
        # For long positions, take profit triggers when price rises above TP
        return current_price >= trade.take_profit_price
    else:  # sell
        # For short positions, take profit triggers when price falls below TP
        return current_price <= trade.take_profit_price


@shared_task
def close_trade_manually(trade_id):
    """Manually close an open trade."""
    logger.info(f"Attempting to manually close trade {trade_id}.")
    try:
        trade = Trade.objects.get(id=trade_id, status__in=["open", "pending_close"])

        # Try to close via Alpaca API if we have order ID
        if trade.alpaca_order_id:
            ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
            ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
            ALPACA_BASE_URL = os.getenv(
                "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
            )

            if ALPACA_API_KEY and ALPACA_SECRET_KEY:
                try:
                    api = tradeapi.REST(
                        ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL
                    )

                    # Submit reduce-only close using live quantity to avoid over-closing
                    try:
                        position = api.get_position(trade.symbol)
                        live_qty = abs(float(position.qty))
                        current_side = "long" if float(position.qty) > 0 else "short"
                        close_side = "sell" if current_side == "long" else "buy"
                    except Exception:
                        live_qty = trade.quantity
                        close_side = "sell" if trade.direction == "buy" else "buy"

                    # Submit a close order. The alpaca-trade-api client may not
                    # support reduce_only in all versions; omit it and rely on qty
                    # derived from live position to avoid over-closing.
                    close_order = api.submit_order(
                        symbol=trade.symbol,
                        qty=live_qty,
                        side=close_side,
                        type="market",
                        time_in_force="gtc",
                    )

                    # Mark trade pending while order is working
                    trade.status = "pending_close"
                    trade.save(update_fields=["status"])

                    # Fetch latest filled order or position price for accurate exit
                    exit_price = None
                    try:
                        order = api.get_order(close_order.id)
                        if getattr(order, "filled_avg_price", None):
                            exit_price = float(order.filled_avg_price)
                    except Exception:
                        pass
                    if exit_price is None:
                        try:
                            pos = api.get_position(trade.symbol)
                            exit_price = float(getattr(pos, "current_price", 0)) or float(getattr(pos, "avg_entry_price", 0))
                        except Exception:
                            pass
                    if exit_price is None:
                        try:
                            ticker = api.get_latest_trade(trade.symbol)
                            exit_price = float(ticker.price)
                        except Exception:
                            exit_price = trade.entry_price  # Fallback

                    # Calculate P&L
                    if trade.direction == "buy":
                        pnl = (float(exit_price) - float(trade.entry_price)) * float(trade.quantity)
                    else:
                        pnl = (float(trade.entry_price) - float(exit_price)) * float(trade.quantity)

                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.realized_pnl = pnl
                    # Only set to manual if no close reason was already set
                    if not trade.close_reason:
                        trade.close_reason = "manual"
                    trade.closed_at = timezone.now()
                    trade.save()

                    logger.info(
                        f"Trade {trade.id} closed via Alpaca API with P&L: ${pnl:.2f}"
                    )

                except Exception as api_error:
                    logger.warning(
                        f"Could not close trade via Alpaca API: {api_error}. Closing locally."
                    )
                    # Best-effort: compute pnl using current market price if available
                    try:
                        ticker = api.get_latest_trade(trade.symbol)
                        market_price = float(getattr(ticker, "price", 0) or 0)
                    except Exception:
                        market_price = float(trade.entry_price or 0)
                    if trade.direction == "buy":
                        pnl = (market_price - float(trade.entry_price)) * float(trade.quantity)
                    else:
                        pnl = (float(trade.entry_price) - market_price) * float(trade.quantity)
                    trade.status = "closed"
                    trade.exit_price = market_price
                    trade.realized_pnl = pnl
                    # Only set to manual if no close reason was already set
                    if not trade.close_reason:
                        trade.close_reason = "manual"
                    trade.closed_at = timezone.now()
                    trade.save()
            else:
                # Close locally without API - estimate using entry (no market access)
                trade.status = "closed"
                trade.exit_price = trade.entry_price
                trade.realized_pnl = 0.0
                # Only set to manual if no close reason was already set
                if not trade.close_reason:
                    trade.close_reason = "manual"
                trade.closed_at = timezone.now()
                trade.save()
        else:
            # Close locally without API - estimate P&L as zero if we cannot fetch price
            trade.status = "closed"
            trade.exit_price = trade.entry_price
            trade.realized_pnl = 0.0
            # Only set to manual if no close reason was already set
            if not trade.close_reason:
                trade.close_reason = "manual"
            trade.closed_at = timezone.now()
            trade.save()

        logger.info(f"Trade {trade.id} for {trade.symbol} manually closed.")
        try:
            # Compute P&L percent for alert
            pnl_percent = None
            if trade.entry_price and trade.quantity:
                try:
                    cost_basis = float(trade.entry_price) * float(abs(trade.quantity))
                    if cost_basis > 0:
                        pnl_percent = (float(trade.realized_pnl or 0) / cost_basis) * 100.0
                except Exception:
                    pnl_percent = None
        except Exception:
            pnl_percent = None

        send_dashboard_update(
            "trade_closed",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "status": trade.status,
                "exit_price": trade.exit_price,
                "realized_pnl": trade.realized_pnl,
                "pnl_percent": pnl_percent,
                "message": "Trade manually closed.",
            },
        )

    except Trade.DoesNotExist:
        error_msg = f"Trade {trade_id} not found or not open."
        logger.warning(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})
    except Exception as e:
        error_msg = f"Error closing trade {trade_id} manually: {e}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})


@shared_task
def create_manual_test_trade(symbol, direction, quantity=None, position_size=None):
    """Create a manual test trade directly to Alpaca API for testing purposes."""
    logger.info(f"Creating manual test trade: {symbol} {direction}")

    # Enforce tracked company requirement for any trade (including manual)
    try:
        from .models import TrackedCompany
        if not TrackedCompany.objects.filter(symbol__iexact=symbol).exists():
            send_dashboard_update(
                "trade_rejected",
                {
                    "symbol": symbol,
                    "reason": "Symbol not in tracked companies",
                    "tag": "Rejected",
                },
            )
            return {
                "success": False,
                "error": "Symbol not in tracked companies"
            }
    except Exception:
        # If lookup fails unexpectedly, be safe and reject
        send_dashboard_update(
            "trade_rejected",
            {"symbol": symbol, "reason": "Tracked company check failed", "tag": "Rejected"},
        )
        return {
            "success": False,
            "error": "Tracked company check failed"
        }

    # Enforce configurable limits here as well
    try:
        config = get_active_trading_config()
    except Exception:
        config = None

    if config:
        concurrent_count = get_effective_concurrent_open_trades_count()
        if config.max_concurrent_open_trades and concurrent_count >= config.max_concurrent_open_trades:
            send_dashboard_update(
                "trade_rejected",
                {
                    "symbol": symbol,
                    "reason": "Concurrent trades limit reached",
                    "limit": config.max_concurrent_open_trades,
                    "tag": "Rejected",
                },
            )
            return {"success": False, "error": "Concurrent trades limit reached"}

        # Exposure check using provided position_size (or estimate from quantity)
        current_exposure = 0.0
        try:
            open_trades = Trade.objects.filter(status__in=["open", "pending", "pending_close"])                
            for t in open_trades:
                if t.entry_price and t.quantity:
                    current_exposure += abs(float(t.entry_price) * float(t.quantity))
        except Exception:
            current_exposure = 0.0

        additional = 0.0
        if position_size:
            additional = float(position_size)
        # If only quantity is known, we will approximate later after fetching price

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not found in environment variables. Cannot execute test trade.")
        send_dashboard_update(
            "trade_error",
            {"error": "Alpaca API keys not configured"},
        )
        return {
            "success": False,
            "error": "Alpaca API keys not configured"
        }

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

    try:
        # Get current stock price for quantity calculation if needed
        try:
            ticker = api.get_latest_trade(symbol)
            current_price = ticker.price
            
            # Calculate quantity if position_size is provided, otherwise use quantity directly
            if position_size and not quantity:
                quantity = max(1, int(position_size / current_price))
            elif not quantity:
                quantity = 1  # Default to 1 share
                
        except Exception as e:
            logger.warning(f"Could not get current price for {symbol}: {e}. Using quantity 1.")
            quantity = quantity or 1
            current_price = 0.0

        # Exposure check after price fetch if needed
        if config and getattr(config, 'max_total_open_exposure', None):
            current_exposure = get_effective_open_exposure()
            additional = float(position_size) if position_size else (float(quantity) * float(current_price))
            projected_exposure = current_exposure + additional
            if projected_exposure > float(config.max_total_open_exposure):
                send_dashboard_update(
                    "trade_rejected",
                    {
                        "symbol": symbol,
                        "reason": "Total exposure limit reached",
                        "current_exposure": current_exposure,
                        "projected_exposure": projected_exposure,
                        "max_exposure": config.max_total_open_exposure,
                        "tag": "Rejected",
                    },
                )
                return {"success": False, "error": "Total exposure limit reached"}

        # Submit order to Alpaca
        logger.info(f"Submitting test order: {symbol}, qty={quantity}, side={direction}")
        order = api.submit_order(
            symbol=symbol,
            qty=quantity,
            side=direction,  # "buy" or "sell"
            type="market",
            time_in_force="gtc",
        )

        # Create minimal trade record for tracking (without analysis)
        # Resolve tracked company if exists
        try:
            from .models import TrackedCompany
            tc = TrackedCompany.objects.filter(symbol__iexact=symbol).first()
        except Exception:
            tc = None

        trade = Trade.objects.create(
            analysis=None,  # No analysis for manual test trades
            symbol=symbol,
            tracked_company=tc,
            direction=direction,
            quantity=quantity,
            entry_price=current_price,
            status="pending",
            alpaca_order_id=order.id,
            opened_at=timezone.now(),
            # Note: Manual test trade - Order ID stored in alpaca_order_id
            take_profit_price_percentage=10.0,
            stop_loss_price_percentage=2.0,
        )

        logger.info(f"Manual test trade created successfully: Trade #{trade.id}, Alpaca Order #{order.id}")
        
        send_dashboard_update(
            "manual_trade_success",
            {
                "trade_id": trade.id,
                "symbol": symbol,
                "direction": direction,
                "quantity": quantity,
                "alpaca_order_id": order.id,
                "current_price": current_price,
            },
        )

        return {
            "success": True,
            "trade_id": trade.id,
            "alpaca_order_id": order.id,
            "message": f"Test trade created: {symbol} {direction} {quantity} shares"
        }

    except Exception as e:
        error_msg = f"Failed to create manual test trade: {str(e)}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"error": error_msg})
        return {
            "success": False,
            "error": error_msg
        }


@shared_task
def update_trade_status():
    """Periodic task to update trade statuses from Alpaca API."""
    logger.info("Updating trade statuses from Alpaca API.")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.warning("Alpaca API keys not configured. Skipping trade status update.")
        return

    try:
        api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

        # 1) Update newly filled entry orders → open
        pending_trades = Trade.objects.filter(status="pending", alpaca_order_id__isnull=False)
        for trade in pending_trades:
            try:
                order = api.get_order(trade.alpaca_order_id)
                if order.status == "filled":
                    trade.status = "open"
                    trade.entry_price = float(order.filled_avg_price or order.limit_price or trade.entry_price)
                    trade.opened_at = timezone.now()
                    trade.save()
                    logger.info(f"Trade {trade.id} status updated to open with entry price {trade.entry_price}")
                    send_dashboard_update("trade_status_updated", {"trade_id": trade.id, "status": "open", "entry_price": trade.entry_price})
                elif order.status in ["cancelled", "rejected"]:
                    trade.status = "failed"
                    trade.save()
                    logger.info(f"Trade {trade.id} failed: {order.status}")
                    send_dashboard_update("trade_status_updated", {"trade_id": trade.id, "status": "failed", "reason": order.status})
            except Exception as e:
                logger.error(f"Error updating status for trade {trade.id}: {e}")

        # 2) Detect working close orders (orders API) → mark trades pending_close
        try:
            open_orders = api.list_orders(status="open", limit=200)
        except Exception:
            open_orders = []

        symbol_to_close_side = {}
        for o in open_orders:
            try:
                symbol_to_close_side.setdefault(o.symbol, set()).add(str(o.side).lower())
            except Exception:
                continue

        candidate_trades = Trade.objects.filter(status__in=["open", "pending_close"])  # monitor both
        for t in candidate_trades:
            try:
                close_side = "sell" if t.direction == "buy" else "buy"
                if close_side in symbol_to_close_side.get(t.symbol, set()):
                    if t.status != "pending_close":
                        t.status = "pending_close"
                        t.save(update_fields=["status"])
                        logger.info(f"Marked trade {t.id} ({t.symbol}) as pending_close due to working {close_side} order")
            except Exception:
                pass

        # 3) Sync closure via positions list → if symbol no longer present, mark newest non-closed trade as closed
        try:
            positions = api.list_positions()
            live_symbols = {p.symbol for p in positions}
        except Exception:
            live_symbols = set()

        to_check = (
            Trade.objects
            .filter(status__in=["open", "pending_close"]) 
            .order_by("-created_at")
        )
        for t in to_check:
            try:
                if t.symbol not in live_symbols and t.status != "closed":
                    # Position no longer exists at broker → close locally
                    # Detect whether another workflow already initiated the close
                    # (e.g. stop_loss / take_profit). If so, we will still
                    # finalize the local record but avoid emitting a duplicate
                    # "trade_closed" activity; the originating workflow will
                    # publish the event.
                    had_close_reason = bool(t.close_reason)
                    try:
                        ticker = api.get_latest_trade(t.symbol)
                        exit_price = float(getattr(ticker, "price", 0) or 0)
                    except Exception:
                        exit_price = t.entry_price or 0.0
                    if t.direction == "buy":
                        pnl = (exit_price - (t.entry_price or 0)) * (t.quantity or 0)
                    else:
                        pnl = ((t.entry_price or 0) - exit_price) * (t.quantity or 0)
                    t.status = "closed"
                    t.exit_price = exit_price
                    t.realized_pnl = pnl
                    t.closed_at = timezone.now()
                    if not t.close_reason:
                        t.close_reason = "market_close"
                    t.save()
                    logger.info(f"Trade {t.id} ({t.symbol}) marked closed after broker position disappeared")
                    # Only emit the activity if THIS function is the source of the
                    # closure (i.e., broker position vanished without a prior
                    # close_reason). If another workflow already set a reason,
                    # skip to avoid duplicate "Trade closed" messages.
                    if not had_close_reason:
                        # Include percent for alert formatting
                        try:
                            cost_basis = float(t.entry_price or 0) * float(abs(t.quantity or 0))
                            pnl_percent = (float(t.realized_pnl or 0) / cost_basis) * 100.0 if cost_basis > 0 else None
                        except Exception:
                            pnl_percent = None
                        send_dashboard_update(
                            "trade_closed",
                            {
                                "trade_id": t.id,
                                "symbol": t.symbol,
                                "exit_price": t.exit_price,
                                "realized_pnl": t.realized_pnl,
                                "pnl_percent": pnl_percent,
                            },
                        )
            except Exception as e:
                logger.error(f"Error syncing closure for trade {t.id}: {e}")

    except Exception as e:
        logger.error(f"Error updating trade statuses: {e}")


@shared_task
def send_bot_heartbeat():
    """Send a periodic heartbeat to Telegram when bot is enabled and alerts allow it.

    Frequency is managed by django-celery-beat; this task also enforces the
    per-settings interval using `last_heartbeat_sent` as a guard.
    """
    try:
        from .utils.telegram import is_alert_enabled, send_telegram_message

        # Check alert toggle first
        if not is_alert_enabled("heartbeat"):
            return

        settings_obj = AlertSettings.objects.order_by("-created_at").first()
        if not settings_obj:
            return

        # Only when bot is enabled
        config = TradingConfig.objects.filter(is_active=True).first()
        if not (config and config.bot_enabled):
            return

        now = timezone.now()
        interval = max(1, int(getattr(settings_obj, "heartbeat_interval_minutes", 30)))
        last_sent = getattr(settings_obj, "last_heartbeat_sent", None)
        if last_sent and (now - last_sent).total_seconds() < interval * 60:
            return

        # Compose message
        try:
            open_positions = Trade.objects.filter(status__in=["open", "pending", "pending_close"]).count()
        except Exception:
            open_positions = 0

        msg = (
            f"🤖 Bot Heartbeat\n"
            f"Status: ENABLED\n"
            f"Open/Pending positions: {open_positions}\n"
            f"Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        ok = send_telegram_message(msg)
        if ok:
            settings_obj.last_heartbeat_sent = now
            settings_obj.save(update_fields=["last_heartbeat_sent"])
    except Exception as e:
        logger.warning(f"Heartbeat send failed: {e}")


@shared_task
def close_all_trades_manually():
    """Close all open trades manually."""
    logger.info("Attempting to close all open trades manually.")
    try:
        # First sync database with Alpaca to ensure consistency
        from .views import get_alpaca_trading_data, sync_alpaca_positions_to_database
        
        alpaca_data = get_alpaca_trading_data()
        alpaca_positions = alpaca_data.get("positions", [])
        sync_alpaca_positions_to_database(alpaca_positions)
        
        # Get all open trades from database (now synced)
        open_trades = Trade.objects.filter(status="open")
        trade_count = open_trades.count()

        if trade_count == 0:
            logger.info("No open trades to close.")
            return {
                "status": "success",
                "message": "No open trades to close",
                "closed_count": 0,
            }

        logger.info(f"Found {trade_count} open trades to close.")

        # Close each trade individually
        closed_count = 0
        failed_count = 0
        errors = []

        for trade in open_trades:
            try:
                # Update status to pending_close first
                trade.status = "pending_close"
                trade.save()
                
                # Use the existing close trade logic
                close_trade_manually.delay(trade.id)
                closed_count += 1
                logger.info(f"Initiated close for trade {trade.id} ({trade.symbol}) - Status updated to pending_close")
            except Exception as e:
                failed_count += 1
                error_msg = (
                    f"Failed to close trade {trade.id} ({trade.symbol}): {str(e)}"
                )
                errors.append(error_msg)
                logger.error(error_msg)

        result_message = (
            f"Close all initiated: {closed_count} successful, {failed_count} failed"
        )
        if errors:
            result_message += (
                f". Errors: {'; '.join(errors[:3])}"  # Limit error messages
            )

        logger.info(result_message)

        # Send dashboard update
        send_dashboard_update(
            "trades_closed_all",
            {
                "closed_count": closed_count,
                "failed_count": failed_count,
                "total_count": trade_count,
                "message": result_message,
            },
        )

        return {
            "status": "success" if failed_count == 0 else "partial",
            "message": result_message,
            "closed_count": closed_count,
            "failed_count": failed_count,
            "errors": errors,
        }

    except Exception as e:
        error_msg = f"Error in close_all_trades_manually: {e}"
        logger.error(error_msg)
        send_dashboard_update("trades_error", {"error": error_msg})
        return {"status": "error", "message": error_msg, "closed_count": 0}


# =============================================================================
# HEALTH MONITORING TASKS
# =============================================================================

import subprocess
import time

@shared_task
def monitor_system_health():
    """Monitor system health and trigger recovery if needed."""
    logger.info("Running system health check")
    
    issues_found = []
    
    # Check for stuck Chrome processes
    chrome_issues = _check_chrome_processes()
    if chrome_issues:
        issues_found.extend(chrome_issues)
    
    # Check worker responsiveness 
    worker_issues = _check_worker_health()
    if worker_issues:
        issues_found.extend(worker_issues)
    
    # Check scraping frequency
    scraping_issues = _check_scraping_frequency()
    if scraping_issues:
        issues_found.extend(scraping_issues)
    
    if issues_found:
        logger.warning(f"Health issues detected: {issues_found}")
        _trigger_recovery(issues_found)
    else:
        logger.info("System health check passed")
    
    return {"status": "completed", "issues": issues_found}


def _check_chrome_processes():
    """Check for stuck or excessive Chrome processes INSIDE the container only."""
    try:
        # This function runs INSIDE the Docker container, so ps only sees container processes
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        chrome_lines = [line for line in result.stdout.split('\n') if 'chrome' in line.lower()]
        
        issues = []
        high_cpu_processes = 0
        playwright_chrome_processes = 0
        
        for line in chrome_lines:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    cpu_usage = float(parts[2])
                    # Only count Playwright Chrome processes (they have specific paths)
                    if 'playwright' in line or '/app/.cache/ms-playwright' in line:
                        playwright_chrome_processes += 1
                        if cpu_usage > 90.0:  # High CPU usage threshold
                            high_cpu_processes += 1
                except ValueError:
                    continue
        
        # Check browser pool stats for better monitoring (thread-local aware)
        try:
            pool_stats = get_browser_pool_stats()
            if 'error' not in pool_stats:
                active_browsers = pool_stats.get('active_browsers', 0)
                max_per_thread = pool_stats.get('max_browsers_per_thread', 2)
                thread_id = pool_stats.get('thread_id', 'unknown')
                
                # Log browser pool status for debugging
                logger.info(f"Browser pool status for thread {thread_id}: {pool_stats}")
                
                # For thread-local pools, we expect:
                # - Up to 4 worker threads (Celery concurrency=4)
                # - Up to 2 browsers per thread
                # - ~3-5 Chrome processes per browser (main + renderers + utilities)
                # Total expected: 4 threads × 2 browsers × 4 processes = ~32 processes max
                reasonable_max = 35  # Allow some buffer for multiple threads
                
                if playwright_chrome_processes > reasonable_max:
                    issues.append(f"Playwright Chrome processes ({playwright_chrome_processes}) exceed reasonable limit for thread-local pools ({reasonable_max})")
            else:
                issues.append(f"Browser pool health check failed: {pool_stats['error']}")
        except Exception as e:
            logger.warning(f"Could not check browser pool stats: {e}")
        
        # Updated threshold for thread-local architecture
        if playwright_chrome_processes > 40:  # Increased from 5 to 40 for thread-local pools
            issues.append(f"Excessive Playwright Chrome processes: {playwright_chrome_processes}")
        
        if high_cpu_processes > 4:  # Increased from 2 to 4 for multiple threads
            issues.append(f"High-CPU Playwright Chrome processes: {high_cpu_processes}")
        
        return issues
    
    except Exception as e:
        logger.error(f"Error checking Chrome processes: {e}")
        return []


def _check_worker_health():
    """Check if Celery worker is responsive."""
    try:
        from celery import current_app
        
        # Try to get worker stats
        inspect = current_app.control.inspect()
        stats = inspect.stats()
        
        if not stats:
            return ["No worker stats available - worker may be unresponsive"]
        
        # Check for any workers
        active_workers = len(stats.keys()) if stats else 0
        if active_workers == 0:
            return ["No active Celery workers found"]
        
        return []
    
    except Exception as e:
        logger.error(f"Error checking worker health: {e}")
        return ["Error checking worker health"]


def _check_scraping_frequency():
    """Check if scraping is happening at expected frequency."""
    try:
        # Check for posts in the last 30 minutes (made more lenient for thread-local pools)
        cutoff = timezone.now() - timedelta(minutes=30)
        recent_posts = Post.objects.filter(created_at__gte=cutoff).count()
        
        if recent_posts == 0:
            return ["No posts created in last 30 minutes - scraping may be stuck"]
        
        return []
    
    except Exception as e:
        logger.error(f"Error checking scraping frequency: {e}")
        return []


def _trigger_recovery(issues):
    """Trigger recovery actions based on detected issues."""
    logger.warning(f"Triggering recovery for issues: {issues}")
    
    # Log the recovery action
    ActivityLog.objects.create(
        activity_type="system_event",
        message="Auto-recovery triggered by health monitor",
        data={
            "issues": issues,
            "action": "auto_recovery_triggered",
            "timestamp": timezone.now().isoformat()
        }
    )
    
    # Be more selective about when to restart worker with thread-local pools
    critical_restart_triggers = [
        "exceed reasonable limit for thread-local pools",  # Only restart for truly excessive processes
        "High-CPU Playwright Chrome processes",
        "No posts created in last 30 minutes"  # Made more lenient - 30 min instead of 15
    ]
    
    should_restart = any(
        any(trigger in issue for trigger in critical_restart_triggers)
        for issue in issues
    )
    
    # Log restart decision for debugging
    if should_restart:
        logger.warning(f"Worker restart triggered by issues: {[issue for issue in issues if any(trigger in issue for trigger in critical_restart_triggers)]}")
    else:
        logger.info(f"Health issues detected but not severe enough to restart worker: {issues}")
    
    if should_restart:
        restart_celery_worker.delay()


@shared_task
def restart_celery_worker():
    """Restart the Celery worker to clear stuck processes."""
    logger.warning("Restarting Celery worker due to health issues")
    
    try:
        ActivityLog.objects.create(
            activity_type="system_event",
            message="Celery worker restart requested by health monitor",
            data={
                "reason": "health_monitor_triggered",
                "timestamp": timezone.now().isoformat()
            }
        )
        
        # Signal for external restart (could be monitored by a watchdog)
        with open('/tmp/restart_worker_signal', 'w') as f:
            f.write(f"restart_requested_at_{int(time.time())}")
        
        logger.info("Worker restart signal created")
        
    except Exception as e:
        logger.error(f"Error creating restart signal: {e}")


@shared_task
def cleanup_orphaned_chrome():
    """Kill orphaned Playwright Chrome processes INSIDE container only."""
    try:
        # This runs INSIDE the Docker container, so only sees container processes
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        chrome_lines = [line for line in result.stdout.split('\n') if 'chrome' in line.lower()]
        
        killed_processes = 0
        for line in chrome_lines:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    pid = int(parts[1])
                    cpu_usage = float(parts[2])
                    
                    # ONLY kill Playwright Chrome processes using >95% CPU
                    # Double-check it's a Playwright process before killing
                    if (cpu_usage > 95.0 and 
                        ('playwright' in line or '/app/.cache/ms-playwright' in line)):
                        subprocess.run(['kill', '-9', str(pid)], capture_output=True)
                        killed_processes += 1
                        logger.warning(f"Killed high-CPU Playwright Chrome process PID {pid}")
                
                except (ValueError, subprocess.SubprocessError):
                    continue
        
        if killed_processes > 0:
            ActivityLog.objects.create(
                activity_type="system_event",
                message=f"Cleaned up {killed_processes} high-CPU Playwright Chrome processes",
                data={
                    "killed_processes": killed_processes,
                    "timestamp": timezone.now().isoformat(),
                    "target": "playwright_chrome_only"
                }
            )
        
        return {"killed_processes": killed_processes}
    
    except Exception as e:
        logger.error(f"Error cleaning up Playwright Chrome processes: {e}")
        return {"error": str(e)}


# NOTE: cleanup_browser_pool_task has been removed as it was incompatible with thread-local browser pools.
# The thread-local browser pools have their own automatic cleanup mechanisms (browser retirement
# based on age and usage) and don't need periodic forced shutdowns that this task was performing.
#
# @shared_task
# def cleanup_browser_pool_task():
#     """[REMOVED] This task was causing browser pool shutdown errors with thread-local pools."""
#     pass


@shared_task(bind=True)
def run_telegram_bot_task(self):
    """
    Celery task to run the Telegram bot.
    
    This runs the bot with polling in a separate async context.
    The task will run indefinitely until stopped.
    """
    try:
        logger.info("Starting Telegram bot task...")
        
        # Import here to avoid circular imports
        from .telegram_bot import start_telegram_bot, stop_telegram_bot
        
        async def run_bot():
            """Run the bot in async context with health monitoring."""
            application = None
            health_monitor_task = None
            try:
                # Import bot service to access health monitoring
                from .telegram_bot import get_bot_service
                
                application = await start_telegram_bot()
                if application:
                    logger.info("Telegram bot started successfully in Celery task")
                    
                    # Start health monitoring in background
                    bot_service = get_bot_service()
                    if bot_service:
                        health_monitor_task = asyncio.create_task(bot_service.monitor_bot_health())
                        logger.info("Telegram bot health monitoring started")
                    
                    # Keep the bot running
                    while not self.request.called_directly:
                        await asyncio.sleep(5)  # Increased from 1s to reduce CPU usage
                        
                        # Check if task should be terminated
                        if hasattr(self, '_should_stop') and self._should_stop:
                            break
                            
                        # Check if health monitor failed
                        if health_monitor_task and health_monitor_task.done():
                            try:
                                # Re-raise any exception from health monitor
                                await health_monitor_task
                            except Exception as e:
                                logger.error(f"Health monitor failed: {e}")
                                # Restart health monitor
                                if bot_service:
                                    health_monitor_task = asyncio.create_task(bot_service.monitor_bot_health())
                else:
                    logger.error("Failed to start Telegram bot in Celery task")
                    
            except Exception as e:
                logger.error(f"Error in Telegram bot task: {e}")
                raise
            finally:
                # Cancel health monitor
                if health_monitor_task and not health_monitor_task.done():
                    health_monitor_task.cancel()
                    try:
                        await health_monitor_task
                    except asyncio.CancelledError:
                        pass
                
                if application:
                    await stop_telegram_bot()
                    logger.info("Telegram bot stopped")
        
        # Run the async function
        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            logger.info("Telegram bot task interrupted")
        except Exception as e:
            logger.error(f"Telegram bot task failed: {e}")
            raise
            
        return {"status": "completed"}
        
    except Exception as e:
        logger.error(f"Error in Telegram bot task: {e}")
        return {"status": "error", "error": str(e)}
