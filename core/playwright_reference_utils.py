# Resource Management in Celery 
# Efficient browser reuse across tasks
from playwright.sync_api import sync_playwright
from celery import Task

class ScrapingTask(Task):
    _browser = None
    
    @property
    def browser(self):
        if self._browser is None:
            playwright = sync_playwright().start()
            self._browser = playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',  # Critical for Docker/limited memory
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )
        return self._browser

@app.task(base=ScrapingTask, bind=True)
def scrape_site(self, url):
    page = self.browser.new_page()
    try:
        page.goto(url, wait_until='networkidle')
        return page.content()
    finally:
        page.close()  # Close page, but keep browser alive

# Memory-Efficient Context Management
@app.task
def scrape_batch(urls):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        # Single browser, multiple contexts for isolation
        for url in urls:
            context = browser.new_context()
            page = context.new_page()
            
            try:
                page.goto(url, timeout=30000)
                # Process...
            finally:
                context.close()  # Frees memory immediately
        
        browser.close()

# Critical Celery-Specific Considerations
# 1. Worker Pool Configuration
# celery_config.py
# Use threads or gevent, NOT prefork for Playwright
worker_pool = 'threads'  # or 'gevent'
worker_concurrency = 4  # Limit based on RAM

# If you must use prefork:
worker_max_tasks_per_child = 50  # Restart workers to free memory

# 2. Timeout Management
@app.task(
    time_limit=120,  # Hard timeout
    soft_time_limit=90  # Soft timeout for cleanup
)
def scrape_with_timeout(url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30000)  # 30s page timeout
            page.goto(url)
            return page.content()
    except SoftTimeLimitExceeded:
        # Graceful cleanup
        browser.close()
        raise

# 3. Memory Leak Prevention
# Create dedicated task queue for scraping with memory limits
CELERY_ROUTES = {
    'scraping.*': {
        'queue': 'scraping',
        'routing_key': 'scraping',
    }
}

# Run worker with memory limit
# celery -A app worker -Q scraping --max-memory-per-child=512000

# Headless Setup
# 1. Use Browser Pool Pattern
from threading import Lock
from collections import deque

class BrowserPool:
    def __init__(self, size=3):
        self.browsers = deque()
        self.lock = Lock()
        self.playwright = sync_playwright().start()
        
        # Pre-create browsers
        for _ in range(size):
            browser = self.playwright.chromium.launch(headless=True)
            self.browsers.append(browser)
    
    def get(self):
        with self.lock:
            return self.browsers.popleft()
    
    def release(self, browser):
        with self.lock:
            self.browsers.append(browser)

# Global pool
browser_pool = BrowserPool()

@app.task
def scrape(url):
    browser = browser_pool.get()
    try:
        page = browser.new_page()
        page.goto(url)
        data = page.content()
        page.close()
        return data
    finally:
        browser_pool.release(browser)

# 2. Docker Configuration
# FROM mcr.microsoft.com/playwright/python:v1.40.0-focal

# # Install Python dependencies
# COPY requirements.txt .
# RUN pip install -r requirements.txt

# Playwright is pre-installed in this image
# Browsers are already downloaded

# 3. Monitoring Zombie Processes
import psutil

@app.task
def cleanup_zombie_browsers():
    """Run periodically to kill hung browser processes"""
    for proc in psutil.process_iter(['pid', 'name']):
        if 'chromium' in proc.info['name'].lower():
            if proc.create_time() < time.time() - 3600:  # 1 hour old
                proc.kill()
                