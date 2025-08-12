from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Trade


class Command(BaseCommand):
    help = "Close duplicate open/pending trades per symbol, preserving the most recent record."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without writing to the DB",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        target_statuses = ["open", "pending", "pending_close"]

        # Collect symbols with more than one non-closed record
        symbols = (
            Trade.objects.filter(status__in=target_statuses)
            .values_list("symbol", flat=True)
            .distinct()
        )

        total_closed = 0
        for symbol in symbols:
            trades = (
                Trade.objects.filter(symbol=symbol, status__in=target_statuses)
                .order_by("-created_at")
            )
            if trades.count() <= 1:
                continue

            keeper = trades.first()
            duplicates = list(trades[1:])

            self.stdout.write(
                self.style.WARNING(
                    f"Symbol {symbol}: keeping trade #{keeper.id}, closing {len(duplicates)} duplicates"
                )
            )

            for dup in duplicates:
                if dry_run:
                    total_closed += 1
                    continue
                dup.status = "closed"
                dup.close_reason = dup.close_reason or "duplicate_sync"
                dup.closed_at = timezone.now()
                # Leave exit_price/realized_pnl blank; this is a data hygiene close
                dup.save(update_fields=["status", "close_reason", "closed_at"])
                total_closed += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would close {total_closed} duplicate trades"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Closed {total_closed} duplicate trades"))


