import logging
from typing import List, Tuple, Optional
import logging
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright
from .browser_manager import get_managed_browser_page
from .models import Post

logger = logging.getLogger(__name__)


def _parse_tweet_card(card) -> Optional[Tuple[str, str, datetime, bool]]:
	try:
		content_el = card.query_selector('div[data-testid="tweetText"]') or card.query_selector('div[lang]')
		content = content_el.inner_text().strip() if content_el else None
		# Find status link
		link_el = card.query_selector('a[href*="/status/"][role="link"]') or card.query_selector('a[href*="/status/"]')
		href = link_el.get_attribute('href') if link_el else None
		# Timestamp
		time_el = card.query_selector('time')
		created_at = None
		if time_el:
			try:
				iso = time_el.get_attribute('datetime')
				if iso:
					created_at = datetime.fromisoformat(iso.replace('Z', '+00:00'))
			except Exception:
				created_at = None
		# Pinned marker
		pinned = bool(card.query_selector('[data-testid="socialContext"]:has-text("Pinned")'))
		if not content or not href:
			return None
		if href.startswith('/'):
			href = f"https://x.com{href}"
		return content, href, created_at or datetime.now(timezone.utc), pinned
	except Exception:
		return None


def _extract_tweets_from_page(page) -> List[Tuple[str, str, datetime, bool]]:
	try:
		page.wait_for_selector('[data-testid="cellInnerDiv"], article[data-testid="tweet"]', timeout=30000)
	except Exception:
		return []
	# Prefer cell containers; fallback to article
	cards = page.query_selector_all('[data-testid="cellInnerDiv"]')
	if not cards:
		cards = page.query_selector_all('article[data-testid="tweet"]')
	results: List[Tuple[str, str, datetime, bool]] = []
	seen = set()
	for card in cards:
		parsed = _parse_tweet_card(card)
		if not parsed:
			continue
		content, url, ts, pinned = parsed
		if url in seen:
			continue
		seen.add(url)
		results.append((content, url, ts, pinned))
	return results


def scrape_twitter_profile(url: str, storage_state: Optional[dict] = None, max_age_hours: Optional[int] = None, backfill: bool = False) -> List[Tuple[str, str, datetime]]:
	"""Scrape tweets from a profile, newest-first, skipping pinned and optionally old tweets.
	Returns list of (content, url, published_at). No DB access here to stay sync-safe.
	"""
	cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours) if max_age_hours else None
	try:
		def _run(page):
			page.set_default_timeout(20000)
			logger.info("[Twitter] Navigating to profile %s", url)
			
			# Force navigate to the chronological timeline instead of algorithmic "Top" tweets
			# This ensures we get recent tweets instead of popular old ones
			latest_url = url.rstrip('/') + '?f=live'  # Force "Latest" tweets
			logger.info(f"[Twitter] Navigating directly to latest tweets: {latest_url}")
			
			try:
				page.goto(latest_url, timeout=60000, wait_until="domcontentloaded")
				page.wait_for_timeout(3000)  # Give more time for latest tweets to load
				logger.info("[Twitter] Successfully loaded latest tweets timeline")
			except Exception as e:
				logger.warning(f"[Twitter] Latest timeline failed, trying main profile: {e}")
				page.goto(url, timeout=60000, wait_until="domcontentloaded")
				page.wait_for_timeout(2000)
			
			# Force refresh to avoid cached content
			logger.info("[Twitter] Refreshing page to get latest content")
			page.reload(wait_until="domcontentloaded")
			page.wait_for_timeout(2000)  # Wait for content to load
			
			# Detect login wall early
			if page.query_selector('a[href="/i/flow/login"], input[name="session[username_or_email]"]'):
				logger.warning("[Twitter] Login wall encountered; session may be missing/expired")
				return []
			
			# Try to switch to "Latest" tweets if available
			try:
				latest_tab = page.query_selector('[role="tab"]:has-text("Latest"), [data-testid="ScrollSnap-List"] a:has-text("Latest")')
				if latest_tab:
					logger.info("[Twitter] Clicking 'Latest' tab to get recent tweets")
					latest_tab.click()
					page.wait_for_timeout(2000)
				else:
					logger.info("[Twitter] No 'Latest' tab found, using default view")
			except Exception as e:
				logger.debug(f"[Twitter] Could not click Latest tab: {e}")
			
			# Wait for tweets to load dynamically (some profiles load slowly)
			logger.info("[Twitter] Waiting for tweets to load...")
			try:
				page.wait_for_selector('[data-testid="cellInnerDiv"], article[data-testid="tweet"]', timeout=10000)
				logger.info("[Twitter] Tweet elements detected")
			except Exception:
				logger.warning("[Twitter] Timeout waiting for tweet elements")
			
			# Check if we can see any tweets at all before scrolling
			initial_check = page.query_selector_all('[data-testid="cellInnerDiv"], article[data-testid="tweet"]')
			if not initial_check:
				logger.warning(f"[Twitter] No tweet elements found initially.")
				
				# Debug: Check what's actually on the page
				page_title = page.title()
				page_url = page.url
				logger.info(f"[Twitter] Page title: '{page_title}', URL: '{page_url}'")
				
				# Check for common error conditions
				login_wall = page.query_selector('a[href="/i/flow/login"], input[name="session[username_or_email]"]')
				suspended = page.query_selector('text="Account suspended"')
				not_found = page.query_selector('text="This account doesn\'t exist"')
				private_account = page.query_selector('text="These Tweets are protected"')
				
				if login_wall:
					logger.error("[Twitter] Login wall detected - session may be expired")
					return []
				elif suspended:
					logger.error("[Twitter] Account is suspended")
					return []
				elif not_found:
					logger.error("[Twitter] Account doesn't exist")
					return []
				elif private_account:
					logger.error("[Twitter] Account is private/protected")
					return []
				
				# Try alternative selectors
				alternative_tweets = page.query_selector_all('article, div[data-testid="tweet"], [data-testid="tweetText"]')
				logger.info(f"[Twitter] Found {len(alternative_tweets)} alternative elements")
				
				# Debug: Show some page content
				try:
					body_text = page.query_selector('body').inner_text()[:500]
					logger.info(f"[Twitter] Page content sample: {body_text}")
				except Exception:
					pass
					
				if not alternative_tweets:
					logger.error("[Twitter] No tweet content found with any selector. Aborting.")
					return []
			last_count = 0
			max_scrolls = 40  # Increase scrolls to get more recent content
			for _ in range(max_scrolls):
				page.wait_for_timeout(1000)
				page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
				# Allow network to settle
				try:
					page.wait_for_load_state("networkidle", timeout=5000)
				except Exception:
					page.wait_for_timeout(800)
				cards = page.query_selector_all('[data-testid="cellInnerDiv"], article[data-testid="tweet"]')
				if cards and len(cards) <= last_count:
					break
				last_count = len(cards)
			items = _extract_tweets_from_page(page)
			logger.info("[Twitter] Extracted %d tweet cards", len(items))
			
			# Debug: Log the timestamps we found
			if items:
				logger.info(f"[Twitter] Sample tweet timestamps:")
				for i, (content, turl, ts, pinned) in enumerate(items[:3]):
					logger.info(f"[Twitter]   Tweet {i+1}: {ts} ({'pinned' if pinned else 'normal'}) - {content[:50]}...")
				if cutoff:
					logger.info(f"[Twitter] Age cutoff: {cutoff}")
			
			# Sort by timestamp desc (newest first)
			items.sort(key=lambda x: x[2], reverse=True)
			out: List[Tuple[str, str, datetime]] = []
			filtered_count = 0
			for content, turl, ts, pinned in items:
				if pinned:
					logger.debug(f"[Twitter] Skipping pinned tweet: {content[:30]}...")
					continue
				if cutoff and ts and ts < cutoff and not backfill:
					logger.debug(f"[Twitter] Skipping old tweet ({ts}): {content[:30]}...")
					filtered_count += 1
					continue
				out.append((content, turl, ts))
			
			if filtered_count > 0:
				logger.info(f"[Twitter] Filtered out {filtered_count} old tweets")
			
			return out
		if storage_state:
			pw = sync_playwright().start()
			browser = pw.chromium.launch(headless=True)
			context = browser.new_context(
				storage_state=storage_state,
				user_agent=(
					"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
					"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
				),
				viewport={"width": 1280, "height": 1600},
			)
			page = context.new_page()
			try:
				return _run(page)
			finally:
				try:
					context.close()
				except Exception:
					pass
				try:
					browser.close()
				except Exception:
					pass
				pw.stop()
		else:
			with get_managed_browser_page() as page:
				return _run(page)
	except Exception as e:
		logger.warning(f"Twitter profile scrape failed for {url}: {e}")
		return []


