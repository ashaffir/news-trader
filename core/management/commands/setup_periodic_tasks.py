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

        # Create crontab (daily at 02:30 by default; configurable via Django Admin)
        daily_230_cron, _ = CrontabSchedule.objects.get_or_create(
            minute='30', hour='2', day_of_week='*', day_of_month='*', month_of_year='*'
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
                'name': 'Chrome Process Cleanup',
                'task': 'core.tasks.cleanup_orphaned_chrome',
                'interval': interval_5_minutes,
                'description': 'Clean up orphaned Chrome processes'
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