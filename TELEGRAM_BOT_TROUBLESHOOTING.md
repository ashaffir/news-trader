# Telegram Bot Troubleshooting Guide

## Common Issue: Singleton Lock Conflict

### Problem
```
ERROR Another Telegram bot instance is already polling (singleton lock not acquired). Skipping start.
Failed to start Telegram bot - check configuration
```

### Root Cause
The Telegram bot uses a Redis-based singleton lock to prevent multiple instances from running simultaneously. This error occurs when:

1. **Container restart loop**: Docker automatically restarts a crashed bot container, but the Redis lock from the previous instance hasn't expired yet
2. **Multiple bot instances**: Both Docker service and Celery task trying to run the bot simultaneously
3. **Stuck lock**: Previous instance crashed without properly releasing the Redis lock

### Solution

#### Step 1: Check Current Lock Status
```bash
# List current Telegram bot locks
docker exec news-trader-celery-1 python manage.py clear_telegram_lock --list-only
```

#### Step 2: Clear Stuck Locks
```bash
# Clear locks with confirmation
docker exec news-trader-celery-1 python manage.py clear_telegram_lock

# Or force clear without confirmation
docker exec news-trader-celery-1 python manage.py clear_telegram_lock --force
```

#### Step 3: Restart the Bot Service
```bash
docker-compose restart telegram-bot
```

#### Step 4: Verify Success
```bash
# Check container status
docker ps | grep telegram

# Check recent logs
docker logs news-trader-telegram-bot-1 --tail 20
```

### Prevention

The bot now includes enhanced lock management:

1. **Shorter lock timeout**: Reduced from 120s to 60s for faster recovery
2. **Stale lock detection**: Automatically clears locks with no expiry
3. **Management command**: Easy tool to clear stuck locks
4. **Better error handling**: More resilient to network issues

### Lock Management Details

#### How the Singleton Lock Works
- **Key**: `telegram_bot_lock:{bot_token}`
- **Value**: `{hostname}:{pid}:{uuid}` (identifies the instance)
- **TTL**: 60 seconds (auto-expires if not refreshed)
- **Refresh**: Every 30 seconds while bot is running

#### Manual Redis Commands
If you need to manually inspect or clear locks:

```bash
# Connect to Redis
docker exec news-trader-redis-1 redis-cli

# List all bot locks
KEYS "telegram_bot_lock:*"

# Check lock details
GET "telegram_bot_lock:8322770552:AAFXiacsy6ffWVS2J3ZaWLyjyvjmFeokWJM"
TTL "telegram_bot_lock:8322770552:AAFXiacsy6ffWVS2J3ZaWLyjyvjmFeokWJM"

# Delete a specific lock (replace with actual key)
DEL "telegram_bot_lock:8322770552:AAFXiacsy6ffWVS2J3ZaWLyjyvjmFeokWJM"
```

### Deployment Configurations

#### Docker Compose (Recommended)
The bot runs as a dedicated service:
```yaml
telegram-bot:
  build:
    context: .
    dockerfile: Dockerfile.bot
  command: python manage.py run_telegram_bot
  depends_on:
    - db
    - redis
  restart: unless-stopped
```

#### Celery Task (Alternative)
You can also run the bot as a Celery task, but **don't run both simultaneously**:
```python
from core.tasks import run_telegram_bot_task
run_telegram_bot_task.delay()
```

### Monitoring

#### Health Checks
The bot includes comprehensive health monitoring:
- API connectivity tests
- Polling status verification
- Automatic recovery from network errors
- Circuit breaker pattern for persistent failures

#### Log Messages to Watch For
✅ **Success indicators:**
- "Telegram bot started successfully!"
- "Telegram polling started successfully"
- "Bot health check passed"

⚠️ **Warning indicators:**
- "Network error in Telegram bot"
- "Bot health check failed"
- "Critical network error detected"

❌ **Error indicators:**
- "Another Telegram bot instance is already polling"
- "Failed to acquire Redis lock"
- "Bot failed health check X times"

### Quick Reference Commands

```bash
# Check bot status
docker ps | grep telegram
docker logs news-trader-telegram-bot-1 --tail 20

# Clear stuck locks
docker exec news-trader-celery-1 python manage.py clear_telegram_lock --force

# Restart bot
docker-compose restart telegram-bot

# Check Redis locks manually
docker exec news-trader-redis-1 redis-cli KEYS "telegram_bot_lock:*"

# View periodic tasks (ensure no duplicate bot tasks)
docker exec news-trader-celery-1 python manage.py shell -c "
from django_celery_beat.models import PeriodicTask
for task in PeriodicTask.objects.filter(task__icontains='telegram'):
    print(f'{task.name}: {task.enabled}')
"
```

### When to Use Each Approach

#### Use Docker Service (Current Setup) When:
- Running in production with Docker Compose
- Want dedicated bot container
- Need easy restart/monitoring capabilities
- Prefer container-based deployment

#### Use Celery Task When:
- Running in development
- Want bot integrated with worker processes
- Need programmatic control over bot lifecycle
- Prefer task-based architecture

**Important**: Never run both simultaneously - they will conflict due to the singleton lock.
