"""
Intelligent News Source Auto-Detection System
Automatically detects the best way to extract news articles from any webpage
"""

import re
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import json
import logging
from datetime import datetime
from collections import Counter
import time

logger = logging.getLogger(__name__)


class NewsSourceAutoDetector:
    """
    Automatically analyzes a news webpage and determines the best extraction strategy
    """
    
    def __init__(self, url):
        self.url = url
        self.domain = urlparse(url).netloc.lower()
        self.soup = None
        self.driver = None
        self.analysis_results = {}
        
    def analyze_source(self):
        """
        Main analysis method that returns optimal extraction configuration
        """
        logger.info(f"Analyzing news source: {self.url}")
        
        # Step 1: Check for RSS/API feeds
        rss_feeds = self._detect_rss_feeds()
        api_endpoints = self._detect_api_endpoints()
        
        # Step 2: Analyze page structure
        page_analysis = self._analyze_page_structure()
        
        # Step 3: Detect article patterns
        article_patterns = self._detect_article_patterns()
        
        # Step 4: Generate optimal configuration
        config = self._generate_optimal_config(rss_feeds, api_endpoints, page_analysis, article_patterns)
        
        self.analysis_results = {
            'url': self.url,
            'domain': self.domain,
            'rss_feeds': rss_feeds,
            'api_endpoints': api_endpoints,
            'page_analysis': page_analysis,
            'article_patterns': article_patterns,
            'recommended_config': config,
            'analyzed_at': datetime.now().isoformat()
        }
        
        return self.analysis_results
    
    def _detect_rss_feeds(self):
        """
        Detect RSS/Atom feeds available on the site
        """
        logger.info("Detecting RSS feeds...")
        feeds = []
        
        try:
            response = requests.get(self.url, timeout=10)
            self.soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for RSS/Atom links in head
            feed_links = self.soup.find_all('link', {'type': ['application/rss+xml', 'application/atom+xml']})
            for link in feed_links:
                href = link.get('href')
                if href:
                    feed_url = urljoin(self.url, href)
                    title = link.get('title', 'RSS Feed')
                    feeds.append({
                        'url': feed_url,
                        'title': title,
                        'type': link.get('type', '')
                    })
            
            # Common RSS URL patterns
            common_rss_paths = [
                '/rss', '/rss.xml', '/feed', '/feed.xml', '/feeds/all.atom.xml',
                '/api/rss', '/rss/news', '/feeds/latest.xml'
            ]
            
            for path in common_rss_paths:
                test_url = urljoin(self.url, path)
                try:
                    test_response = requests.head(test_url, timeout=5)
                    if test_response.status_code == 200:
                        content_type = test_response.headers.get('content-type', '')
                        if 'xml' in content_type or 'rss' in content_type:
                            feeds.append({
                                'url': test_url,
                                'title': f'RSS Feed ({path})',
                                'type': 'application/rss+xml'
                            })
                except:
                    continue
                    
        except Exception as e:
            logger.warning(f"Error detecting RSS feeds: {e}")
        
        return feeds
    
    def _detect_api_endpoints(self):
        """
        Detect potential API endpoints
        """
        logger.info("Detecting API endpoints...")
        apis = []
        
        try:
            # Check for common API patterns in page source
            if self.soup:
                scripts = self.soup.find_all('script')
                for script in scripts:
                    if script.string:
                        # Look for API endpoints in JavaScript
                        api_patterns = [
                            r'["\']([^"\']*(?:api|json)[^"\']*)["\']',
                            r'fetch\(["\']([^"\']+)["\']',
                            r'axios\.get\(["\']([^"\']+)["\']'
                        ]
                        
                        for pattern in api_patterns:
                            matches = re.findall(pattern, script.string, re.IGNORECASE)
                            for match in matches:
                                if 'api' in match.lower() or 'json' in match.lower():
                                    full_url = urljoin(self.url, match)
                                    apis.append({
                                        'url': full_url,
                                        'type': 'detected_in_js',
                                        'method': 'GET'
                                    })
            
            # Test common API paths
            common_api_paths = [
                '/api/articles', '/api/news', '/api/posts', '/api/v1/articles',
                '/wp-json/wp/v2/posts', '/api/content', '/json/news'
            ]
            
            for path in common_api_paths:
                test_url = urljoin(self.url, path)
                try:
                    test_response = requests.head(test_url, timeout=5)
                    if test_response.status_code == 200:
                        content_type = test_response.headers.get('content-type', '')
                        if 'json' in content_type:
                            apis.append({
                                'url': test_url,
                                'type': 'rest_api',
                                'method': 'GET'
                            })
                except:
                    continue
                    
        except Exception as e:
            logger.warning(f"Error detecting API endpoints: {e}")
        
        return apis
    
    def _analyze_page_structure(self):
        """
        Analyze the overall page structure and technology
        """
        logger.info("Analyzing page structure...")
        
        analysis = {
            'requires_javascript': False,
            'has_infinite_scroll': False,
            'framework_detected': None,
            'total_links': 0,
            'article_links': 0,
            'meta_info': {}
        }
        
        try:
            if self.soup:
                # Detect JavaScript frameworks
                scripts = self.soup.find_all('script', src=True)
                script_srcs = [script.get('src', '') for script in scripts]
                
                for src in script_srcs:
                    if 'react' in src.lower():
                        analysis['framework_detected'] = 'React'
                        analysis['requires_javascript'] = True
                    elif 'angular' in src.lower():
                        analysis['framework_detected'] = 'Angular'
                        analysis['requires_javascript'] = True
                    elif 'vue' in src.lower():
                        analysis['framework_detected'] = 'Vue'
                        analysis['requires_javascript'] = True
                
                # Check for infinite scroll indicators
                body_text = self.soup.get_text().lower()
                if any(phrase in body_text for phrase in ['load more', 'infinite scroll', 'lazy load']):
                    analysis['has_infinite_scroll'] = True
                
                # Count links
                all_links = self.soup.find_all('a', href=True)
                analysis['total_links'] = len(all_links)
                
                # Count potential article links
                article_links = [link for link in all_links 
                               if self._looks_like_article_url(link.get('href', ''))]
                analysis['article_links'] = len(article_links)
                
                # Get meta information
                title_tag = self.soup.find('title')
                analysis['meta_info']['title'] = title_tag.text.strip() if title_tag else ''
                
                meta_desc = self.soup.find('meta', attrs={'name': 'description'})
                analysis['meta_info']['description'] = meta_desc.get('content', '') if meta_desc else ''
                
        except Exception as e:
            logger.warning(f"Error analyzing page structure: {e}")
        
        return analysis
    
    def _detect_article_patterns(self):
        """
        Use browser automation to detect article patterns
        """
        logger.info("Detecting article patterns with browser...")
        
        patterns = {
            'selectors_found': [],
            'common_patterns': [],
            'article_containers': [],
            'title_patterns': [],
            'content_patterns': [],
            'link_patterns': []
        }
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])    
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 2000},
                )
                page = context.new_page()
                page.goto(self.url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_selector("body", timeout=10000)

                article_selectors = [
                    'article', '.article', '[class*="article"]',
                    '.post', '[class*="post"]', '.story', '[class*="story"]',
                    '.news-item', '[class*="news"]', '.card', '[class*="card"]',
                    '.item', '[class*="item"]', '.entry', '[class*="entry"]',
                    'a[href*="/202"]', 'a[href*="/news/"]', 'a[href*="/article/"]'
                ]

                for selector in article_selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        if elements:
                            valid_elements = []
                            for elem in elements[:10]:
                                try:
                                    text = (elem.inner_text() or '').strip()
                                    href = elem.get_attribute('href')
                                    if ((text and len(text) > 20) or (href and self._looks_like_article_url(href))):
                                        valid_elements.append(elem)
                                except Exception:
                                    continue
                            if valid_elements:
                                patterns['selectors_found'].append({
                                    'selector': selector,
                                    'count': len(valid_elements),
                                    'total_found': len(elements)
                                })
                    except Exception:
                        continue
            
            # Analyze successful selectors for patterns
            patterns['common_patterns'] = self._analyze_selector_patterns(patterns['selectors_found'])
            
            # Find title patterns
            patterns['title_patterns'] = self._detect_title_patterns()
            
            # Find content patterns  
            patterns['content_patterns'] = self._detect_content_patterns()
            
        except Exception as e:
            logger.warning(f"Error detecting article patterns: {e}")
        finally:
            pass
        
        return patterns
    
    def _looks_like_article_url(self, url):
        """
        Check if a URL looks like an article URL
        """
        if not url:
            return False
        
        url_lower = url.lower()
        
        # Positive indicators
        article_indicators = [
            '/202', '/article/', '/news/', '/story/', '/post/',
            '/blog/', '/press-release/', '/report/'
        ]
        
        # Negative indicators
        non_article_indicators = [
            'javascript:', 'mailto:', '#', '/tag/', '/category/',
            '/author/', '/search/', '/login/', '/register/',
            '.pdf', '.jpg', '.png', '.gif', '/contact/', '/about/'
        ]
        
        # Check positive indicators
        has_positive = any(indicator in url_lower for indicator in article_indicators)
        
        # Check negative indicators
        has_negative = any(indicator in url_lower for indicator in non_article_indicators)
        
        return has_positive and not has_negative
    
    def _analyze_selector_patterns(self, selectors_found):
        """
        Analyze which selectors work best
        """
        if not selectors_found:
            return []
        
        # Sort by quality score (valid articles found vs total elements)
        scored_selectors = []
        for sel in selectors_found:
            if sel['total_found'] > 0:
                quality_score = sel['count'] / sel['total_found']
                scored_selectors.append({
                    'selector': sel['selector'],
                    'quality_score': quality_score,
                    'article_count': sel['count']
                })
        
        # Sort by quality score and article count
        scored_selectors.sort(key=lambda x: (x['quality_score'], x['article_count']), reverse=True)
        
        return scored_selectors[:5]  # Return top 5
    
    def _detect_title_patterns(self):
        """
        Detect common title element patterns
        """
        title_selectors = ['h1', 'h2', 'h3', 'h4', '.title', '[class*="title"]', '[class*="headline"]']
        patterns = []
        
        for selector in title_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                valid_titles = []
                
                for elem in elements[:5]:
                    try:
                        text = elem.text.strip()
                        if text and 10 <= len(text) <= 200:  # Reasonable title length
                            valid_titles.append(text)
                    except:
                        continue
                
                if valid_titles:
                    patterns.append({
                        'selector': selector,
                        'count': len(valid_titles),
                        'samples': valid_titles[:3]
                    })
            except:
                continue
        
        return patterns
    
    def _detect_content_patterns(self):
        """
        Detect common content/description patterns
        """
        content_selectors = ['p', '.content', '.summary', '.excerpt', '[class*="summary"]', '[class*="description"]']
        patterns = []
        
        for selector in content_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                valid_content = []
                
                for elem in elements[:5]:
                    try:
                        text = elem.text.strip()
                        if text and 20 <= len(text) <= 500:  # Reasonable content length
                            valid_content.append(text[:100] + '...' if len(text) > 100 else text)
                    except:
                        continue
                
                if valid_content:
                    patterns.append({
                        'selector': selector,
                        'count': len(valid_content),
                        'samples': valid_content[:2]
                    })
            except:
                continue
        
        return patterns
    
    def _generate_optimal_config(self, rss_feeds, api_endpoints, page_analysis, article_patterns):
        """
        Generate the optimal scraping configuration based on analysis
        """
        config = {
            'recommended_method': 'web',  # Default
            'scraping_method': 'web',
            'selectors': {},
            'alternative_methods': [],
            'confidence_score': 0.0,
            'reasoning': []
        }
        
        # Check if the URL itself is an RSS feed
        url_is_rss = (self.url.endswith('.xml') or 
                     'rss' in self.url.lower() or 
                     'feed' in self.url.lower() or
                     'atom' in self.url.lower())
        
        if url_is_rss:
            config['recommended_method'] = 'rss'
            config['is_rss_url'] = True
            config['confidence_score'] += 0.5
            config['reasoning'].append("URL appears to be an RSS feed directly")
            return config
        
        # Determine best method
        if rss_feeds:
            config['recommended_method'] = 'rss'
            config['scraping_method'] = 'web'  # Keep web as fallback
            config['rss_feed_url'] = rss_feeds[0]['url']
            config['confidence_score'] += 0.4
            config['reasoning'].append("RSS feed available - most reliable method")
        
        if api_endpoints:
            if config['recommended_method'] == 'rss':
                config['recommended_method'] = 'both'
            else:
                config['recommended_method'] = 'api'
            config['api_endpoint'] = api_endpoints[0]['url']
            config['confidence_score'] += 0.3
            config['reasoning'].append("API endpoint detected")
        
        # Generate selectors for web scraping
        if article_patterns['common_patterns']:
            best_pattern = article_patterns['common_patterns'][0]
            
            config['selectors'] = {
                'container': best_pattern['selector'],
                'title': [p['selector'] for p in article_patterns['title_patterns'][:3]] or ['h3', 'h2', 'h1'],
                'content': [p['selector'] for p in article_patterns['content_patterns'][:3]] or ['p', '.content'],
                'link': 'a'
            }
            
            config['confidence_score'] += min(best_pattern['quality_score'], 0.3)
            config['reasoning'].append(f"Found {best_pattern['article_count']} articles with '{best_pattern['selector']}'")
        
        # Adjust for JavaScript requirements
        if page_analysis.get('requires_javascript'):
            config['requires_javascript'] = True
            config['confidence_score'] -= 0.1
            config['reasoning'].append("Requires JavaScript - may need browser automation")
        
        # Add alternative methods
        if rss_feeds and config['recommended_method'] != 'rss':
            config['alternative_methods'].append('rss')
        if api_endpoints and 'api' not in config['recommended_method']:
            config['alternative_methods'].append('api')
        
        return config
    
    def save_analysis(self, filepath=None):
        """
        Save analysis results to JSON file
        """
        if not filepath:
            domain_clean = re.sub(r'[^\w\-_]', '_', self.domain)
            filepath = f'analysis_{domain_clean}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        with open(filepath, 'w') as f:
            json.dump(self.analysis_results, f, indent=2)
        
        logger.info(f"Analysis saved to {filepath}")
        return filepath


def analyze_news_source(url):
    """
    Convenience function to analyze a news source
    """
    detector = NewsSourceAutoDetector(url)
    results = detector.analyze_source()
    return results


if __name__ == "__main__":
    # Example usage
    test_urls = [
        "https://www.reuters.com/world/",
        "https://www.bbc.com/news",
        "https://techcrunch.com/"
    ]
    
    for url in test_urls:
        print(f"\n=== Analyzing {url} ===")
        results = analyze_news_source(url)
        print(f"Recommended method: {results['recommended_config']['recommended_method']}")
        print(f"Confidence: {results['recommended_config']['confidence_score']:.2f}")
        print(f"Reasoning: {results['recommended_config']['reasoning']}")
