# Browser Pool Solution: Preventing Chrome Process Accumulation

## Problem Analysis

The original issue was Chrome processes accumulating and not being cleaned up properly during scraping operations. This happened because:

1. **Thread-local persistence**: The original `playwright_utils.py` created one browser instance per Celery worker thread and kept it alive indefinitely
2. **No task-level cleanup**: Browser instances accumulated because they were only cleaned up on thread exit, not after each task
3. **Celery worker lifecycle**: Workers handle many tasks over time, so browser instances persisted across hundreds of scraping operations

## Solution: Thread-Local Managed Browser Pool

### Key Features

1. **Thread-Local Isolation**: Each thread (Celery worker) has its own browser instances - no cross-thread sharing
2. **Limited Pool Size**: Maximum of 2 browser instances per thread (configurable)
3. **Browser Retirement**: Browsers are retired based on age (30 minutes) or usage count (50 operations)
4. **Automatic Cleanup**: Expired browsers are automatically cleaned up per thread
5. **Thread-Safe**: Complete thread isolation prevents Playwright threading errors
6. **Graceful Shutdown**: Proper cleanup on exit per thread

### Implementation Components

#### 1. Browser Manager (`core/browser_manager.py`)
- **ThreadLocalBrowserPool**: Main class that manages browser lifecycle per thread
- **BrowserInstance**: Container for browser with metadata (creation time, usage count)
- **Thread-Local Storage**: Each thread maintains its own browser pool queue and active browser registry
- **Context Managers**: `get_managed_browser_context()` and `get_managed_browser_page()`
- **Pool Statistics**: Monitoring and health check capabilities per thread

#### 2. Updated Scraping Tasks (`core/tasks.py`)
- Replaced `get_browser_page()` with `get_managed_browser_page()`
- Added browser pool health monitoring to Chrome process checks
- Reduced threshold for "excessive" Chrome processes from 10 to 5

#### 3. Proactive Cleanup Task
- **cleanup_browser_pool_task**: Runs every 30 minutes to force browser pool cleanup
- Logs statistics before and after cleanup
- Integrated into periodic task system

#### 4. Enhanced Monitoring
- Browser pool statistics in health checks
- Comparison of actual Chrome processes vs expected pool size
- Activity logging for all cleanup operations

## Configuration

### Browser Pool Settings
```python
# Default settings in ThreadLocalBrowserPool
max_browsers_per_thread = 2    # Maximum browsers per thread (was 3 global)
max_browser_age_minutes = 30   # Browser retirement age
max_browser_usage = 50         # Browser retirement usage count (reduced from 100)
browser_timeout_seconds = 5    # Timeout for getting browser from thread pool (reduced)
```

### Chrome Launch Arguments
Optimized for containerized environments:
```python
--no-sandbox
--disable-dev-shm-usage
--disable-background-timer-throttling
--disable-backgrounding-occluded-windows
--disable-renderer-backgrounding
--no-first-run
--disable-extensions
--disable-web-security
--disable-features=VizDisplayCompositor
--disable-gpu
--disable-software-rasterizer
```

## Deployment

### 1. Update Periodic Tasks
Run the management command to add the new browser pool cleanup task:

```bash
python manage.py setup_periodic_tasks
```

This adds:
- **Browser Pool Cleanup**: Runs every 30 minutes
- Updates existing Chrome process monitoring

### 2. Restart Celery Workers
Restart your Celery workers to use the new browser management:

```bash
# In Docker environment
docker-compose restart celery-1
```

### 3. Monitor Browser Pool
Check browser pool health via Django admin or logs:

```python
from core.browser_manager import get_browser_pool_stats
stats = get_browser_pool_stats()
# Returns: {"active_browsers": 2, "available_in_pool": 1, "max_pool_size": 3, ...}
```

## Testing

### Manual Testing
```bash
# Test basic functionality
python manage.py test_browser_pool

# Test concurrent usage
python manage.py test_browser_pool --test-concurrent

# Test cleanup
python manage.py test_browser_pool --test-cleanup

# Stress test
python manage.py test_browser_pool --test-stress
```

### Monitoring Commands
```bash
# Check current Chrome processes
docker exec news-trader-celery-1 ps aux | grep chrome

# Check browser pool stats in logs
docker logs news-trader-celery-1 | grep "Browser pool"

# Force browser pool cleanup
docker exec news-trader-celery-1 python manage.py shell -c "
from core.tasks import cleanup_browser_pool_task
cleanup_browser_pool_task.delay()
"
```

## Expected Results

### Before (Original thread-local approach)
- Chrome processes would accumulate: 10, 15, 20+ processes
- Memory usage would grow over time
- No automatic cleanup until worker restart
- Threading errors: "cannot switch to a different thread"

### After (Thread-local managed pool approach)
- Chrome processes stay within limits: typically 1-4 processes (2 per worker thread)
- Consistent memory usage per thread
- Automatic cleanup every 30 minutes per thread
- Browsers retired after 30 minutes or 50 uses
- **No threading errors** - complete thread isolation

## Performance Benefits

1. **Thread Safety**: Complete elimination of Playwright threading errors
2. **Memory Efficiency**: Browser reuse reduces memory overhead per thread
3. **Process Limits**: Hard limit on concurrent Chrome processes per thread
4. **Auto-Recovery**: Automatic cleanup prevents accumulation per thread
5. **Better Monitoring**: Real-time visibility into browser usage per thread

## Threading Fix Details

### Problem Solved
The original browser pool shared browser instances across threads, violating Playwright's thread-safety requirements. This caused:
```
ERROR Error in managed browser context: cannot switch to a different thread
```

### Solution Implemented
- **Thread-Local Storage**: Each Celery worker thread maintains its own browser pool
- **No Cross-Thread Sharing**: Browser instances are never shared between threads
- **Thread-Aware Cleanup**: Each thread cleans up its own browser instances
- **Isolated Statistics**: Pool stats are per-thread, not global

### Technical Implementation
```python
# Thread-local storage for browser pools
self._thread_local = threading.local()

def _get_thread_pool(self):
    """Get or create thread-local browser pool data"""
    if not hasattr(self._thread_local, 'pool'):
        self._thread_local.pool = Queue(maxsize=self.max_browsers_per_thread)
        self._thread_local.active_browsers = {}
        self._thread_local.thread_id = threading.get_ident()
    return self._thread_local
```

## Rollback Plan

If issues occur, you can temporarily revert by changing the import in `core/tasks.py`:

```python
# Rollback to old approach
from core.playwright_utils import get_browser_page as get_managed_browser_page
```

However, this would bring back the Chrome process accumulation issue.

## Long-term Maintenance

1. **Monitor browser pool stats** in health checks
2. **Adjust pool size** if needed based on workload
3. **Update retirement thresholds** if browsers need longer/shorter lifespans
4. **Review logs** for any browser creation/cleanup errors

The managed browser pool approach fundamentally solves the Chrome process accumulation by ensuring proper lifecycle management and proactive cleanup.
