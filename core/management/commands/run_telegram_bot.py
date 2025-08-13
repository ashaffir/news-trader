"""
Django management command to run the Telegram bot.

Usage:
    python manage.py run_telegram_bot

This command starts the Telegram bot with polling to handle incoming messages.
"""

import asyncio
import logging
from django.core.management.base import BaseCommand
from core.telegram_bot import start_telegram_bot, stop_telegram_bot

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the Telegram bot for interactive commands'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-polling',
            action='store_true',
            help='Disable polling (useful for webhook mode)',
        )

    def handle(self, *args, **options):
        """Run the Telegram bot."""
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        
        try:
            # Run the async bot
            asyncio.run(self._run_bot(options))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Telegram bot stopped by user'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Telegram bot error: {e}'))
            logger.exception("Telegram bot failed")

    async def _run_bot(self, options):
        """Async function to run the bot."""
        try:
            application = await start_telegram_bot()
            if application:
                self.stdout.write(self.style.SUCCESS('Telegram bot started successfully!'))
                self.stdout.write('Press Ctrl+C to stop the bot')
                
                # Keep the bot running
                try:
                    while True:
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    pass
            else:
                self.stdout.write(self.style.ERROR('Failed to start Telegram bot - check configuration'))
        finally:
            await stop_telegram_bot()
            self.stdout.write(self.style.SUCCESS('Telegram bot stopped'))
