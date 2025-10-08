from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule


class Command(BaseCommand):
    help = "Sets up initial periodic tasks for admin control (replaces static CELERY_BEAT_SCHEDULE)"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Setting up periodic tasks for admin control...")
        )

        # Create intervals
        interval_1_minute, _ = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.MINUTES,
        )
        
        interval_5_minutes, _ = IntervalSchedule.objects.get_or_create(
            every=5,
            period=IntervalSchedule.MINUTES,
        )
        
        interval_1_hour, _ = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.HOURS,
        )

        interval_30_minutes, _ = IntervalSchedule.objects.get_or_create(
            every=30,
            period=IntervalSchedule.MINUTES,
        )

        interval_10_minutes, _ = IntervalSchedule.objects.get_or_create(
            every=10,
            period=IntervalSchedule.MINUTES,
        )
        interval_2_minutes, _ = IntervalSchedule.objects.get_or_create(
            every=2,
            period=IntervalSchedule.MINUTES,
        )

        # Create crontab (daily at 02:30 by default; configurable via Django Admin)
        daily_230_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='30', hour='2', day_of_week='*', day_of_month='*', month_of_year='*'
        )
        # Weekday enable at 13:25 UTC (5 minutes before open) Mon-Fri
        weekday_preopen_1325_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='25', hour='13', day_of_week='1-5', day_of_month='*', month_of_year='*'
        )

        # Weekends at 02:30 UTC (Saturday and Sunday)
        weekend_230_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='30', hour='2', day_of_week='6,0', day_of_month='*', month_of_year='*'
        )

        # Friday pre-close at 19:55 UTC (market close ~20:00 UTC)
        friday_preclose_1955_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='55', hour='19', day_of_week='5', day_of_month='*', month_of_year='*'
        )
        # Weekday open at 13:30 UTC and backup at 13:31 UTC (Mon-Fri)
        weekday_open_1330_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='30', hour='13', day_of_week='1-5', day_of_month='*', month_of_year='*'
        )
        weekday_open_1331_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='31', hour='13', day_of_week='1-5', day_of_month='*', month_of_year='*'
        )

        # Monthly cleanup on the 1st day of each month at 03:00 UTC
        monthly_0300_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='3', day_of_week='*', day_of_month='1', month_of_year='*'
        )

        # Create periodic tasks
        tasks = [
            {
                'name': 'Scrape Posts Every 5 Minutes',
                'task': 'core.tasks.scrape_posts',
                'interval': interval_5_minutes,
                'description': 'Scrape news posts from all enabled sources'
            },
            {
                'name': 'Update Trade Status Every Minute',
                'task': 'core.tasks.update_trade_status', 
                'interval': interval_1_minute,
                'description': 'Check and update trade statuses from Alpaca API'
            },
            {
                'name': 'Close Expired Positions Every Hour',
                'task': 'core.tasks.close_expired_positions',
                'interval': interval_1_hour,
                'description': 'Check for and close expired trading positions'
            },
            {
                'name': 'Monitor Stop/Take Profit Levels Every Minute',
                'task': 'core.tasks.monitor_local_stop_take_levels',
                'interval': interval_1_minute,
                'description': 'Monitor local stop loss and take profit levels'
            },
            {
                'name': 'Bot Heartbeat (Telegram)',
                'task': 'core.tasks.send_bot_heartbeat',
                'interval': interval_30_minutes,
                'description': 'Send periodic heartbeat to Telegram when bot is enabled'
            },
            {
                'name': 'System Health Monitor',
                'task': 'core.tasks.monitor_system_health',
                'interval': interval_10_minutes,
                'description': 'Monitor system health and trigger auto-recovery'
            },
            {
                'name': 'Daily Database Backup (Local)',
                'task': 'core.tasks.backup_database',
                'crontab': daily_230_cron,
                'description': 'Create local compressed PostgreSQL backup (configurable time)'
            },
            {
                'name': 'Daily Log Maintenance',
                'task': 'core.tasks.cleanup_old_logs',
                'crontab': daily_230_cron,
                'description': 'Remove old log files based on LOG_RETENTION_DAYS'
            },
            {
                'name': 'Daily ActivityLog Prune',
                'task': 'core.tasks.prune_activity_log',
                'crontab': daily_230_cron,
                'description': 'Delete ActivityLog rows older than days set in ConfigControl: activitylog_retention_days'
            },
            {
                'name': 'Chrome Process Cleanup',
                'task': 'core.tasks.cleanup_orphaned_chrome',
                'interval': interval_5_minutes,
                'description': 'Clean up orphaned Chrome processes'
            },
            {
                'name': 'Disable Bot On Weekends',
                'task': 'core.tasks.disable_bot_on_weekends',
                'crontab': weekend_230_cron,
                'description': 'Automatically disable trading bot on Saturdays and Sundays'
            },
            {
                'name': 'weekend_shutoff',
                'task': 'core.tasks.weekend_shutoff',
                'crontab': friday_preclose_1955_cron,
                'description': 'Pre-weekend: cancel open orders, close trades, disable bot (Fri 19:55 UTC)'
            },
            # Autostart removed: manual control + weekend/weekday tasks
            {
                'name': 'Enable Bot On Weekdays (pre-open)',
                'task': 'core.tasks.enable_bot_on_weekdays',
                'crontab': weekday_preopen_1325_cron,
                'description': 'Ensure bot is enabled before weekday market open'
            },
            {
                'name': 'Process Overnight At Open',
                'task': 'core.tasks.process_overnight_posts',
                'crontab': weekday_open_1330_cron,
                'description': 'Zero-latency overnight processing at market open (Mon-Fri 13:30 UTC)'
            },
            {
                'name': 'Process Overnight Open Backup',
                'task': 'core.tasks.process_overnight_posts',
                'crontab': weekday_open_1331_cron,
                'description': 'Backup trigger 1 minute after open (Mon-Fri 13:31 UTC)'
            },
            {
                'name': 'Intraday Pre-Close Enforcement',
                'task': 'core.tasks.enforce_intraday_preclose',
                'interval': interval_2_minutes,
                'description': 'If intraday trading enabled, close all positions before market close'
            },
            {
                'name': 'Watchdog: Requeue Waiting Confirmations',
                'task': 'core.tasks.requeue_stale_waiting_confirmations',
                'interval': interval_2_minutes,
                'description': 'Re-enqueue analyses stuck in waiting_confirmation > 2 minutes'
            },
            {
                'name': 'Monthly Old Data Cleanup',
                'task': 'core.tasks.cleanup_old_data',
                'crontab': monthly_0300_cron,
                'description': 'Clean up old posts and API responses based on posts_retention_days config (PRESERVES posts with trades - monthly on 1st at 03:00 UTC)'
            },

        ]

        for task_config in tasks:
            defaults = {
                'task': task_config['task'],
                'description': task_config['description'],
                'enabled': True,
            }
            if 'interval' in task_config:
                defaults['interval'] = task_config['interval']
            if 'crontab' in task_config:
                defaults['crontab'] = task_config['crontab']

            task, created = PeriodicTask.objects.get_or_create(
                name=task_config['name'],
                defaults=defaults
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Created: {task_config['name']}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"⚠️  Already exists: {task_config['name']}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                "\n🎉 Setup complete! You can now manage all task intervals via Django Admin:"
            )
        )
        self.stdout.write("   📍 Go to: /admin/django_celery_beat/periodictask/")
        self.stdout.write("   🔧 Edit intervals, enable/disable tasks, add new ones")
        self.stdout.write("   ⏰ Changes take effect immediately without restarting Celery Beat") 