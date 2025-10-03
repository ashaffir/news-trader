from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Analysis, TradingConfig
from core.tasks import enter_confirmation_check


class Command(BaseCommand):
    help = (
        "Immediately trigger entry confirmation for analyses that are waiting. "
        "This includes: (1) overnight eligible analyses and (2) any analyses "
        "already in waiting_confirmation state."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print what would run without dispatching tasks")

    def handle(self, *args, **options):
        dry = options.get("dry_run", False)

        cfg = TradingConfig.objects.filter(is_active=True).first()
        min_conf = float(getattr(cfg, "min_confidence_threshold", 0.7) or 0.7)

        triggered = 0

        # A) Overnight: eligible or waiting, not stale, confident, buy/sell
        overnight_qs = (
            Analysis.objects.filter(
                post__overnight=True,
                post__is_stale=False,
                direction__in=["buy", "sell"],
                confidence__gte=min_conf,
            )
            .only("id", "enter_status")
        )

        for a in overnight_qs:
            try:
                if a.enter_status not in ("eligible", "waiting_confirmation"):
                    continue
                if dry:
                    self.stdout.write(f"[DRY] Overnight trigger analysis #{a.id}")
                else:
                    if a.enter_status != "waiting_confirmation":
                        a.enter_status = "waiting_confirmation"
                        a.save(update_fields=["enter_status"])
                    enter_confirmation_check.delay(a.id)
                    triggered += 1
            except Exception as e:
                self.stderr.write(f"Overnight trigger failed for {a.id}: {e}")

        # B) Non-overnight waiting_confirmation
        waiting_qs = Analysis.objects.filter(
            post__overnight=False,
            enter_status="waiting_confirmation",
        ).only("id")

        for a in waiting_qs:
            try:
                if dry:
                    self.stdout.write(f"[DRY] Trigger waiting_confirmation analysis #{a.id}")
                else:
                    enter_confirmation_check.delay(a.id)
                    triggered += 1
            except Exception as e:
                self.stderr.write(f"Trigger failed for {a.id}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Triggered confirmations for {triggered} analyses"))


