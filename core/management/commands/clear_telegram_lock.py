"""
Management command to clear stuck Telegram bot Redis locks.

This command helps resolve situations where the Telegram bot can't start
due to a singleton lock being stuck in Redis from a previous crashed instance.

Usage:
    python manage.py clear_telegram_lock
    python manage.py clear_telegram_lock --force  # Clear without confirmation
"""
from django.core.management.base import BaseCommand
import redis
import os


class Command(BaseCommand):
    help = "Clear stuck Telegram bot Redis locks to resolve startup conflicts"

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Clear locks without confirmation prompt'
        )
        parser.add_argument(
            '--list-only',
            action='store_true',
            help='Only list existing locks without clearing them'
        )

    def handle(self, *args, **options):
        try:
            # Connect to Redis
            url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
            if not url or not url.startswith("redis"):
                self.stdout.write(
                    self.style.ERROR("No Redis URL found in environment variables")
                )
                return

            redis_client = redis.Redis.from_url(url)
            
            # Find all Telegram bot locks
            lock_pattern = "telegram_bot_lock:*"
            locks = redis_client.keys(lock_pattern)
            
            if not locks:
                self.stdout.write(
                    self.style.SUCCESS("✅ No Telegram bot locks found in Redis")
                )
                return
            
            self.stdout.write(f"Found {len(locks)} Telegram bot lock(s):")
            
            for lock in locks:
                lock_key = lock.decode('utf-8')
                try:
                    lock_value = redis_client.get(lock)
                    if lock_value:
                        value_str = lock_value.decode('utf-8')
                        ttl = redis_client.ttl(lock)
                        ttl_str = f"{ttl}s" if ttl > 0 else "no expiry" if ttl == -1 else "expired"
                        self.stdout.write(f"  🔒 {lock_key}")
                        self.stdout.write(f"     Value: {value_str}")
                        self.stdout.write(f"     TTL: {ttl_str}")
                except Exception as e:
                    self.stdout.write(f"  🔒 {lock_key} (error reading: {e})")
            
            if options['list_only']:
                return
            
            # Confirm deletion unless forced
            if not options['force']:
                confirm = input(f"\nDo you want to clear {len(locks)} lock(s)? [y/N]: ")
                if confirm.lower() not in ['y', 'yes']:
                    self.stdout.write("❌ Operation cancelled")
                    return
            
            # Clear the locks
            cleared_count = 0
            for lock in locks:
                try:
                    result = redis_client.delete(lock)
                    if result:
                        cleared_count += 1
                        lock_key = lock.decode('utf-8')
                        self.stdout.write(
                            self.style.SUCCESS(f"✅ Cleared lock: {lock_key}")
                        )
                except Exception as e:
                    lock_key = lock.decode('utf-8')
                    self.stdout.write(
                        self.style.ERROR(f"❌ Failed to clear lock {lock_key}: {e}")
                    )
            
            if cleared_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f"\n🎉 Successfully cleared {cleared_count} lock(s)")
                )
                self.stdout.write("You can now restart the Telegram bot:")
                self.stdout.write("  docker-compose restart telegram-bot")
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️ No locks were cleared")
                )
                
        except redis.ConnectionError:
            self.stdout.write(
                self.style.ERROR("❌ Failed to connect to Redis. Is Redis running?")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error: {e}")
            )
