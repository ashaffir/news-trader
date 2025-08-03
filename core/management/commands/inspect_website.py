from django.core.management.base import BaseCommand
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from urllib.parse import urlparse


class Command(BaseCommand):
    help = "Inspect a website's structure to help configure scraping selectors"

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='URL to inspect')

    def handle(self, *args, **options):
        url = options['url']
        
        self.stdout.write(f"Inspecting website structure: {url}")
        
        # Set up headless Chrome
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            driver.get(url)
            
            self.stdout.write(f"\nPage title: {driver.title}")
            
            # Test common article container selectors
            selectors_to_test = [
                'article',
                '.article',
                '.story',
                '.post',
                '.card',
                '.item',
                '.entry',
                '.news-item',
                '.content-item',
                '[class*="article"]',
                '[class*="story"]',
                '[class*="news"]',
                '[class*="post"]',
                '[class*="item"]',
                '[class*="card"]'
            ]
            
            self.stdout.write("\n=== Potential Article Containers ===")
            container_candidates = []
            
            for selector in selectors_to_test:
                elements = driver.find_elements('css selector', selector)
                if elements:
                    count = len(elements)
                    self.stdout.write(f"{selector}: {count} elements")
                    
                    # If reasonable number of elements (likely articles)
                    if 3 <= count <= 50:
                        container_candidates.append((selector, count))
            
            # Analyze the most promising containers
            if container_candidates:
                self.stdout.write("\n=== Analyzing Top Candidates ===")
                
                # Sort by count and take the most promising
                container_candidates.sort(key=lambda x: abs(x[1] - 10))  # Prefer ~10 articles
                best_selector = container_candidates[0][0]
                
                self.stdout.write(f"\nAnalyzing: {best_selector}")
                
                elements = driver.find_elements('css selector', best_selector)
                
                for i, element in enumerate(elements[:3]):
                    self.stdout.write(f"\n--- Element {i+1} ---")
                    
                    # Look for titles
                    title_selectors = ['h1', 'h2', 'h3', 'h4', '.title', '[class*="title"]']
                    for title_sel in title_selectors:
                        title_elems = element.find_elements('css selector', title_sel)
                        if title_elems:
                            title_text = title_elems[0].text.strip()[:100]
                            self.stdout.write(f"Title ({title_sel}): {title_text}")
                            break
                    
                    # Look for links
                    links = element.find_elements('css selector', 'a')
                    if links:
                        href = links[0].get_attribute('href')
                        self.stdout.write(f"Link: {href}")
                    
                    # Show element text preview
                    text_preview = element.text.strip()[:200]
                    self.stdout.write(f"Text preview: {text_preview}")
                
                # Generate configuration suggestion
                domain = urlparse(url).netloc
                self.stdout.write(f"\n=== Suggested Configuration ===")
                self.stdout.write(f"Add this to _get_site_specific_selectors() in core/tasks.py:")
                self.stdout.write(f"""
        '{domain}': {{
            'container': '{best_selector}',
            'title': ['h3', 'h2', 'h1'],
            'content': ['p', '.content', '.summary'],
            'link': 'a'
        }},""")
            
            else:
                self.stdout.write(self.style.WARNING("No clear article containers found. This website might be challenging to scrape."))
        
        finally:
            driver.quit()
            
        self.stdout.write(self.style.SUCCESS("\nInspection complete!")) 