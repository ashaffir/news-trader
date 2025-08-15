# Browser Pool Shutdown Fix

## Problem Diagnosed

The Celery workers were experiencing the following error during scraping tasks:

```
ERROR Error in managed browser context: Browser pool is shutdown
ERROR Error in Playwright scraping https://www.cnbc.com/latest/: Browser pool is shutdown
```

## Root Cause Analysis

### The Issue
The thread-local browser pool was using a **global shutdown flag** (`self._shutdown = True`) that affected all threads when any single thread called `shutdown()`. This created several problems:

1. **Premature Shutdown**: When management commands (like Django shell commands) ended, they triggered `atexit` handlers that called `shutdown()` on the browser pool
2. **Global Impact**: The shutdown affected all Celery worker threads, not just the thread that initiated shutdown
3. **Permanent Shutdown**: Once marked as shutdown, the pool couldn't be used by any thread until the worker process restarted

### Why It Happened
```python
# BEFORE: Global shutdown flag (problematic)
class ThreadLocalBrowserPool:
    def __init__(self):
        self._shutdown = False  # ❌ Global flag affected all threads
    
    def shutdown(self):
        self._shutdown = True   # ❌ Shutdown affected entire pool
```

## Solution Implemented

### Thread-Local Shutdown State
Moved the shutdown flag from global scope to thread-local storage:

```python
# AFTER: Thread-local shutdown flag (fixed)
def _get_thread_pool(self):
    if not hasattr(self._thread_local, 'pool'):
        self._thread_local.shutdown = False  # ✅ Per-thread shutdown flag
    return self._thread_local

def shutdown(self):
    thread_pool = self._get_thread_pool()
    thread_pool.shutdown = True  # ✅ Only affects current thread
```

### Key Changes Made

1. **Removed Global Shutdown Flag**
   - Eliminated `self._shutdown` global variable
   - Added `thread_pool.shutdown` per-thread flag

2. **Updated All Shutdown Checks**
   - `get_browser()`: Now checks `thread_pool.shutdown` instead of `self._shutdown`
   - `return_browser()`: Uses thread-local shutdown state
   - `_cleanup_expired_browsers()`: Respects per-thread shutdown

3. **Removed Automatic Shutdown Registration**
   ```python
   # BEFORE: Automatic shutdown on exit (caused problems)
   atexit.register(_browser_pool.shutdown)
   
   # AFTER: No automatic shutdown (fixed)
   # Note: No atexit registration - let threads manage their own cleanup
   ```

4. **Enhanced Error Messages**
   ```python
   # BEFORE: Generic error message
   raise RuntimeError("Browser pool is shutdown")
   
   # AFTER: Thread-specific error message
   raise RuntimeError(f"Browser pool for thread {thread_pool.thread_id} is shutdown")
   ```

## Testing Results

### Before Fix
```
ERROR Error in managed browser context: Browser pool is shutdown
ERROR Error in Playwright scraping https://www.cnbc.com/latest/: Browser pool is shutdown
```

### After Fix
```
✅ INFO Initialized ThreadLocalBrowserPool: max_per_thread=2, max_age=30min, max_usage=50
✅ INFO Creating new Playwright browser instance for thread 281472518910368
✅ INFO Created browser instance 281472524539216 for thread 281472518910368
✅ INFO Playwright scraping completed for CNBC - Latest: 0 headlines
✅ Task succeeded in 8.28s: None
```

### Concurrent Task Testing
Successfully tested 3 concurrent scraping tasks:
- Each task got its own thread and browser instance
- No interference between threads
- All tasks completed successfully

## Benefits

1. **Thread Isolation**: Each Celery worker thread manages its own browser pool lifecycle
2. **No Global Interference**: Shutdown in one thread doesn't affect other threads
3. **Resilient Operation**: Browser pool can continue operating even if individual threads shut down
4. **Better Error Messages**: Clear indication of which thread has issues
5. **Maintained Efficiency**: Still benefits from browser reuse within each thread

## Technical Details

### Thread-Local Storage Structure
Each thread maintains:
```python
self._thread_local = threading.local()
# Per thread:
#   - pool: Queue(maxsize=2)           # Browser instance queue
#   - active_browsers: {}              # Active browser registry
#   - thread_id: int                   # Thread identifier
#   - shutdown: bool                   # Thread-local shutdown flag
```

### Browser Pool Statistics
Pool stats are now per-thread:
```python
{
    "thread_id": 281472518910368,
    "active_browsers": 1,
    "available_in_pool": 0,
    "max_browsers_per_thread": 2,
    "in_use": 1,
    "pool_utilization": "50.0%"
}
```

## Configuration

The thread-local browser pool maintains the same configuration options:
- `max_browsers_per_thread = 2` (reduced from global 3)
- `max_browser_age_minutes = 30`
- `max_browser_usage = 50` (reduced from 100)

## Monitoring

Chrome process count is still monitored, but now with thread-aware expectations:
- **Expected processes**: ~2-4 per active worker thread
- **Warning threshold**: >5 total Chrome processes (down from 10)
- **Health monitoring**: Still checks for excessive processes

The fix ensures that browser pools operate independently per thread while maintaining the Chrome process management benefits of the original solution.
