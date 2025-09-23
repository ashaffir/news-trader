# System Tasks Overview

This document provides a comprehensive overview of all main tasks in the news-trader system.

## Task Table

| Name | Concise Description | Type | Default Configuration |
|------|-------------------|------|----------------------|
| `scrape_posts` | Scrape news posts from all enabled sources | Scraping | Every 5 minutes, requires bot_enabled=True |
| `scrape_twitter_profile_task` | Scrape specific Twitter profile for posts | Scraping | On-demand, 2 min timeout, max_age_hours=168 |
| `check_twitter_session_health` | Monitor Twitter session validity | Scraping | On-demand |
| `analyze_post` | Analyze scraped post with LLM for trading signals | Analysis | On-demand, requires bot_enabled=True, configurable LLM model |
| `execute_trade` | Execute trades based on analysis results | Trading | On-demand, requires bot_enabled=True |
| `create_new_trade` | Create new position for analyzed trading opportunity | Trading | On-demand via execute_trade |
| `adjust_position_risk` | Adjust TP/SL for existing positions | Trading | On-demand via execute_trade |
| `close_trade_due_to_conflict` | Close trades due to conflicting analysis | Trading | On-demand via execute_trade |
| `close_expired_positions` | Close positions exceeding maximum hold time | Trading | Every 1 hour |
| `monitor_local_stop_take_levels` | Monitor positions for TP/SL triggers | Trading | Every 1 minute |
| `close_trade_manually` | Manually close specific open trade | Trading | On-demand |
| `create_manual_test_trade` | Create manual test trade for testing | Trading | On-demand, configurable symbol/direction/quantity |
| `close_all_trades_manually` | Close all open trades at once | Trading | On-demand |
| `update_trade_status` | Sync trade statuses with Alpaca API | Trading | Every 1 minute |
| `weekend_shutoff` | Pre-weekend safety: close trades, disable bot | Trading | Friday 19:55 UTC |
| `send_bot_heartbeat` | Send periodic status updates to Telegram | Operations | Every 30 minutes when bot enabled |
| `monitor_system_health` | Monitor system health and trigger recovery | Operations | Every 10 minutes |
| `restart_celery_worker` | Restart Celery worker to clear stuck processes | Operations | On-demand |
| `cleanup_orphaned_chrome` | Kill orphaned Chrome processes | Operations | Every 5 minutes |
| `disable_bot_on_weekends` | Disable trading bot on weekends | Operations | Saturday/Sunday 02:30 UTC |
| `enforce_bot_autostart` | Auto enable/disable bot based on market hours | Operations | Every 2 minutes when autostart enabled |
| `run_telegram_bot_task` | Run Telegram bot for notifications | Operations | Background service |
| `backup_database` | Create compressed PostgreSQL backup | Data Management | Daily at 02:30 UTC |
| `restore_database` | Restore database from backup | Data Management | On-demand |
| `cleanup_old_logs` | Remove old log files | Data Management | Daily at 02:30 UTC, configurable retention days |
| `prune_activity_log` | Delete old ActivityLog entries | Data Management | Daily at 02:30 UTC, configurable retention days |
| `cleanup_old_data` | Clean up old posts and API responses | Data Management | Monthly on 1st at 03:00 UTC, preserves posts with trades |

## Task Categories

### Trading Tasks
Tasks that handle actual trading operations, position management, and risk controls.

### Analysis Tasks  
Tasks that process scraped content with LLM models to generate trading signals.

### Scraping Tasks
Tasks that collect data from external sources (RSS feeds, Twitter, APIs).

### Operations Tasks
Tasks that monitor system health, manage infrastructure, and handle notifications.

### Data Management Tasks
Tasks that handle data cleanup, backups, and database maintenance.

## Configuration Notes

- **Bot Control**: Most trading and analysis tasks require `bot_enabled=True` in TradingConfig
- **Manual Override**: Tasks with `manual_test=True` parameter bypass bot_enabled checks
- **Scheduling**: Periodic tasks are managed via Django Admin at `/admin/django_celery_beat/periodictask/`
- **Dependencies**: Trading tasks require valid Alpaca API credentials and market hours
- **Timeouts**: Some tasks have built-in timeouts (e.g., Twitter scraping: 2 minutes)
- **Retention**: Data cleanup tasks use configurable retention periods from ConfigControl model

## Task Dependencies

```
scrape_posts → analyze_post → execute_trade → {create_new_trade, adjust_position_risk, close_trade_due_to_conflict}
                                ↓
                        monitor_local_stop_take_levels
                                ↓
                        update_trade_status
```

All tasks are implemented as Celery shared tasks in `core/tasks.py` and can be triggered manually via Django Admin or programmatically.
