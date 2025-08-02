# Admin Setup Guide - PostgreSQL & Task Management

## ✅ FIXED: PostgreSQL Local Configuration

The database configuration has been updated to use **localhost** instead of Docker's "db" hostname.

### Database Settings (already configured):
```python
# news_trader/settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "news_trader"),
        "USER": os.getenv("DB_USER", "news_trader"), 
        "PASSWORD": os.getenv("DB_PASSWORD", "news_trader"),
        "HOST": os.getenv("DB_HOST", "localhost"),  # ✅ FIXED: Changed from "db"
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}
```

### Optional: Create .env file for custom settings:
```bash
# Create .env file in project root (optional)
DB_NAME=news_trader
DB_USER=your_postgres_user
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432
```

## 🎛️ NEW: Admin-Controlled Task Scheduling

### Setup Complete:
- ✅ django-celery-beat installed
- ✅ Database migrations applied
- ✅ Initial periodic tasks created
- ✅ Static CELERY_BEAT_SCHEDULE removed

### Access Task Management:
1. **Start server**: `python manage.py runserver`
2. **Go to admin**: `http://localhost:8000/admin/`
3. **Task management**: `/admin/django_celery_beat/periodictask/`

### Available Tasks (now admin-controlled):
| Task Name | Function | Default Interval |
|-----------|----------|------------------|
| Scrape Posts Every 5 Minutes | `core.tasks.scrape_posts` | 5 minutes |
| Update Trade Status Every Minute | `core.tasks.update_trade_status` | 1 minute |
| Close Expired Positions Every Hour | `core.tasks.close_expired_positions` | 1 hour |
| Monitor Stop/Take Profit Levels Every Minute | `core.tasks.monitor_local_stop_take_levels` | 1 minute |

### How to Change Intervals:
1. Go to `/admin/django_celery_beat/periodictask/`
2. Click on any task to edit
3. Change the "Interval" field
4. Save - **changes take effect immediately!**

### Start Celery Workers:
```bash
# Terminal 1: Celery Worker
celery -A news_trader worker -l info

# Terminal 2: Celery Beat (scheduler)  
celery -A news_trader beat -l info

# Terminal 3: Django Server
python manage.py runserver
```

## 🚀 What Changed:

### Before (Static):
- Intervals hardcoded in `settings.py`
- Required code changes to modify
- Needed server restart for changes

### After (Admin-Controlled):
- All intervals configurable via Django Admin
- Live changes without restarts
- Easy to add/remove/modify tasks
- Professional task management interface

### Admin Features:
- ✅ Enable/disable individual tasks
- ✅ Change intervals on-the-fly
- ✅ Add new periodic tasks
- ✅ View task history and logs
- ✅ Cron-style scheduling available
- ✅ One-time scheduled tasks 