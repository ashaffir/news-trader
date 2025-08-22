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

        # Collect tracked companies (fallback to symbol when FK missing) with more than one non-closed record
        from core.models import TrackedCompany
        # Prefer grouping by tracked_company when available to align with new constraint
        tracked_ids = (
            Trade.objects.filter(status__in=target_statuses, tracked_company__isnull=False)
            .values_list("tracked_company", flat=True)
            .distinct()
        )
        symbols = (
            Trade.objects.filter(status__in=target_statuses, tracked_company__isnull=True)
            .values_list("symbol", flat=True)
            .distinct()
        )

        total_closed = 0
        # Deduplicate per tracked company
        for tc_id in tracked_ids:
            trades = (
                Trade.objects.filter(tracked_company_id=tc_id, status__in=target_statuses)
                .order_by("-created_at")
            )
            if trades.count() <= 1:
                continue
            keeper = trades.first()
            duplicates = list(trades[1:])
            tc = TrackedCompany.objects.filter(id=tc_id).first()
            label = tc.symbol if tc else f"company:{tc_id}"
            self.stdout.write(
                self.style.WARNING(
                    f"Company {label}: keeping trade #{keeper.id}, closing {len(duplicates)} duplicates"
                )
            )
            for dup in duplicates:
                if dry_run:
                    total_closed += 1
                    continue
                dup.status = "closed"
                dup.close_reason = dup.close_reason or "duplicate_sync"
                dup.closed_at = timezone.now()
                dup.save(update_fields=["status", "close_reason", "closed_at"])
                total_closed += 1

        # Deduplicate legacy symbol-based trades without FK
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
                dup.save(update_fields=["status", "close_reason", "closed_at"])
                total_closed += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would close {total_closed} duplicate trades"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Closed {total_closed} duplicate trades"))


