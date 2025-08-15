"""
Management command to test the new managed browser pool functionality.
"""
from django.core.management.base import BaseCommand
from core.browser_manager import get_managed_browser_page, get_browser_pool_stats, cleanup_browser_pool
import time


class Command(BaseCommand):
    help = "Test the managed browser pool functionality and Chrome process management"

    def add_arguments(self, parser):
        parser.add_argument(
            '--test-concurrent',
            action='store_true',
            help='Test concurrent browser usage'
        )
        parser.add_argument(
            '--test-cleanup',
            action='store_true', 
            help='Test browser pool cleanup'
        )
        parser.add_argument(
            '--test-stress',
            action='store_true',
            help='Stress test with many browser operations'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Testing Managed Browser Pool...")
        )

        # Test basic functionality
        self.test_basic_functionality()
        
        if options['test_concurrent']:
            self.test_concurrent_usage()
            
        if options['test_cleanup']:
            self.test_cleanup()
            
        if options['test_stress']:
            self.test_stress()
            
        self.stdout.write(
            self.style.SUCCESS("Browser pool testing completed!")
        )

    def test_basic_functionality(self):
        """Test basic browser pool functionality"""
        self.stdout.write("Testing basic browser functionality...")
        
        # Get initial stats
        stats = get_browser_pool_stats()
        self.stdout.write(f"Initial pool stats: {stats}")
        
        # Test a simple page load
        try:
            with get_managed_browser_page() as page:
                page.goto("https://example.com", timeout=10000)
                title = page.title()
                self.stdout.write(f"✅ Successfully loaded page: {title}")
                
            # Check stats after usage
            stats = get_browser_pool_stats()
            self.stdout.write(f"Pool stats after page load: {stats}")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error in basic test: {e}")
            )

    def test_concurrent_usage(self):
        """Test concurrent browser usage"""
        self.stdout.write("Testing concurrent browser usage...")
        
        import threading
        
        def worker(worker_id):
            try:
                with get_managed_browser_page() as page:
                    page.goto("https://httpbin.org/delay/1", timeout=15000)
                    self.stdout.write(f"✅ Worker {worker_id} completed")
            except Exception as e:
                self.stdout.write(f"❌ Worker {worker_id} failed: {e}")
        
        # Start multiple workers
        threads = []
        for i in range(4):  # Test with 4 concurrent workers
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
            
        # Wait for all to complete
        for t in threads:
            t.join()
            
        # Check final stats
        stats = get_browser_pool_stats()
        self.stdout.write(f"Pool stats after concurrent test: {stats}")

    def test_cleanup(self):
        """Test browser pool cleanup"""
        self.stdout.write("Testing browser pool cleanup...")
        
        # Get stats before cleanup
        stats_before = get_browser_pool_stats()
        self.stdout.write(f"Stats before cleanup: {stats_before}")
        
        # Perform cleanup
        cleanup_browser_pool()
        
        # Get stats after cleanup
        stats_after = get_browser_pool_stats()
        self.stdout.write(f"Stats after cleanup: {stats_after}")
        
        self.stdout.write("✅ Cleanup test completed")

    def test_stress(self):
        """Stress test with many browser operations"""
        self.stdout.write("Running stress test with 10 sequential browser operations...")
        
        for i in range(10):
            try:
                with get_managed_browser_page() as page:
                    page.goto("https://httpbin.org/get", timeout=10000)
                    self.stdout.write(f"✅ Stress test operation {i+1} completed")
                    
                # Check stats every few operations
                if i % 3 == 0:
                    stats = get_browser_pool_stats()
                    self.stdout.write(f"   Pool stats at operation {i+1}: {stats}")
                    
            except Exception as e:
                self.stdout.write(f"❌ Stress test operation {i+1} failed: {e}")
                
        # Final stats
        final_stats = get_browser_pool_stats()
        self.stdout.write(f"Final pool stats: {final_stats}")
