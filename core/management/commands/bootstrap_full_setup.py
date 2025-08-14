from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import TradingConfig, AlertSettings, Source


class Command(BaseCommand):
    help = "Bootstrap full system setup: superuser, configs, periodic tasks, and default sources. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--superuser",
            type=str,
            default="alfreds",
            help="Username for the default superuser (default: alfreds)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default="!Q2w3e4r%T",
            help="Password for the default superuser (default: !Q2w3e4r%T)",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="admin@example.com",
            help="Email for the default superuser",
        )
        parser.add_argument(
            "--with-cnbc-latest",
            dest="with_cnbc_latest",
            action="store_true",
            help="Create CNBC Latest as a default source (https://www.cnbc.com/latest/)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting full bootstrap setup..."))

        # 1) Create superuser if not exists
        User = get_user_model()
        su_username = options["superuser"]
        su_password = options["password"]
        su_email = options["email"]

        try:
            user = User.objects.filter(username=su_username).first()
            if user is None:
                user = User.objects.create_superuser(
                    username=su_username, email=su_email, password=su_password
                )
                self.stdout.write(self.style.SUCCESS(f"✅ Created superuser: {su_username}"))
            else:
                if not user.is_superuser:
                    user.is_staff = True
                    user.is_superuser = True
                    user.save(update_fields=["is_staff", "is_superuser"])
                self.stdout.write(self.style.WARNING(f"⚠️  Superuser already exists: {su_username}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to ensure superuser: {e}"))
            raise

        # 2) Ensure TradingConfig exists (start with bot disabled by default)
        trading_defaults = dict(
            is_active=True,
            bot_enabled=False,
            trading_enabled=True,
            default_position_size=100.0,
            max_position_size=1000.0,
            stop_loss_percentage=5.0,
            take_profit_percentage=10.0,
            min_confidence_threshold=0.7,
            max_daily_trades=10,
            llm_model="gpt-3.5-turbo",
            market_hours_only=True,
        )
        config, created = TradingConfig.objects.get_or_create(
            name="Default Trading Configuration", defaults=trading_defaults
        )
        if not created:
            # Ensure key flags are set appropriately (do not auto-enable bot)
            updated = False
            if not config.is_active:
                config.is_active = True
                updated = True
            if not config.trading_enabled:
                config.trading_enabled = True
                updated = True
            if updated:
                config.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ TradingConfig ready: {config.name} (active={config.is_active}, bot_enabled={config.bot_enabled}, trading_enabled={config.trading_enabled})"
            )
        )

        # 3) Ensure AlertSettings exists (enable heartbeat by default)
        alerts, _ = AlertSettings.objects.get_or_create(
            defaults=dict(
                enabled=True,
                bot_status_enabled=True,
                order_open_enabled=True,
                order_close_enabled=True,
                trading_limit_enabled=True,
                heartbeat_enabled=True,
                heartbeat_interval_minutes=30,
            )
        )
        self.stdout.write(self.style.SUCCESS("✅ AlertSettings ready"))

        # 4) Create CNBC Latest as default source if requested
        if options.get("with_cnbc_latest"):
            try:
                cnbc_source, created = Source.objects.get_or_create(
                    url="https://www.cnbc.com/latest/",
                    defaults=dict(
                        name="CNBC - Latest",
                        description="CNBC Latest news page",
                        scraping_method="web",
                        data_extraction_config={},
                        scraping_enabled=True,
                        scraping_interval_minutes=5,
                    ),
                )
                if created:
                    self.stdout.write(self.style.SUCCESS("✅ Created source: CNBC - Latest"))
                else:
                    self.stdout.write(self.style.WARNING("⚠️  Source already exists: CNBC - Latest"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Failed to ensure CNBC Latest source: {e}"))
                raise

        # 5) Register periodic tasks (via existing command)
        try:
            from django.core.management import call_command

            call_command("setup_periodic_tasks")
            self.stdout.write(self.style.SUCCESS("✅ Periodic tasks registered"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to set up periodic tasks: {e}"))
            raise

        # 6) Optional: small sanity ping
        _ = timezone.now()

        self.stdout.write(self.style.SUCCESS("🎉 Full bootstrap completed"))


