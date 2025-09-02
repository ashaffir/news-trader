from django.core.management.base import BaseCommand, CommandError
from core.models import TwitterSession
from core.twitter_login_flow import create_twitter_session_interactive
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create a new Twitter session for authenticated scraping"

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Twitter username (without @)'
        )
        parser.add_argument(
            '--email', 
            type=str,
            help='Email address for Twitter account'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password for Twitter account'
        )
        parser.add_argument(
            '--headless',
            action='store_true',
            help='Run in headless mode (default: False for easier debugging)'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("🐦 Creating Twitter session...")
        )

        username = options.get('username')
        email = options.get('email') 
        password = options.get('password')
        headless = options.get('headless', False)

        # Interactive input if not provided
        if not username:
            username = input("Enter Twitter username (without @): ").strip()
        if not email:
            email = input("Enter email address: ").strip()
        if not password:
            import getpass
            password = getpass.getpass("Enter password: ").strip()

        if not all([username, email, password]):
            raise CommandError("Username, email, and password are required")

        self.stdout.write(f"Creating session for @{username}...")
        self.stdout.write(f"Headless mode: {headless}")

        try:
            # Check if session already exists
            existing = TwitterSession.objects.filter(username=username).first()
            if existing:
                self.stdout.write(
                    self.style.WARNING(f"Session for @{username} already exists")
                )
                overwrite = input("Overwrite existing session? (y/N): ").strip().lower()
                if overwrite != 'y':
                    self.stdout.write("Cancelled")
                    return

            # Create the session
            session = create_twitter_session_interactive(
                username=username,
                email=email, 
                password=password,
                headless=headless
            )

            if session:
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Successfully created session for @{username}")
                )
                self.stdout.write(f"Session ID: {session.id}")
                self.stdout.write(f"Status: {session.status}")
            else:
                self.stdout.write(
                    self.style.ERROR("❌ Failed to create session")
                )

        except Exception as e:
            logger.error(f"Error creating Twitter session: {e}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(f"❌ Error: {e}")
            )
            raise CommandError(f"Failed to create Twitter session: {e}")
