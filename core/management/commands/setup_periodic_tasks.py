from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule


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
        ]

        for task_config in tasks:
            task, created = PeriodicTask.objects.get_or_create(
                name=task_config['name'],
                defaults={
                    'task': task_config['task'],
                    'interval': task_config['interval'],
                    'description': task_config['description'],
                    'enabled': True,
                }
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