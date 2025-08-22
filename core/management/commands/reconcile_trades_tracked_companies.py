import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Trade, TrackedCompany


class Command(BaseCommand):
    help = (
        "Reconcile trades against TrackedCompany: "
        "- If a trade.symbol matches a tracked company, set tracked_company. "
        "- If no match: close at broker if open/pending/pending_close; delete if closed/cancelled/failed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not perform changes, just print actions.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # Build lookup of symbol -> TrackedCompany
        companies = {tc.symbol.upper(): tc for tc in TrackedCompany.objects.all()}

        updated_fk = 0
        close_enqueued = 0
        deleted = 0

        # First, map missing FKs where possible
        for trade in Trade.objects.filter(tracked_company__isnull=True):
            symbol = (trade.symbol or "").upper().strip()
            company = companies.get(symbol)
            if company:
                if dry_run:
                    self.stdout.write(f"Would set tracked_company for Trade#{trade.id} -> {company.symbol}")
                else:
                    trade.tracked_company = company
                    trade.save(update_fields=["tracked_company"]) 
                updated_fk += 1

        # Then, handle truly unmatched trades
        unmatched_qs = Trade.objects.filter(tracked_company__isnull=True)
        for trade in unmatched_qs:
            status = trade.status
            if status in ("open", "pending", "pending_close"):
                # Close at broker by symbol using Alpaca REST when possible
                if dry_run:
                    self.stdout.write(f"Would close at broker Trade#{trade.id} ({trade.symbol})")
                else:
                    api_key = os.getenv("ALPACA_API_KEY")
                    secret_key = os.getenv("ALPACA_SECRET_KEY")
                    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
                    try:
                        import alpaca_trade_api as tradeapi
                        if api_key and secret_key:
                            api = tradeapi.REST(api_key, secret_key, base_url=base_url)
                            try:
                                pos = api.get_position(trade.symbol)
                                live_qty = abs(float(getattr(pos, "qty", 0) or 0))
                                if live_qty > 0:
                                    current_side = "long" if float(getattr(pos, "qty", 0)) > 0 else "short"
                                    close_side = "sell" if current_side == "long" else "buy"
                                    api.submit_order(
                                        symbol=trade.symbol,
                                        qty=live_qty,
                                        side=close_side,
                                        type="market",
                                        time_in_force="gtc",
                                    )
                                    # Mark pending while broker processes
                                    trade.status = "pending_close"
                                    trade.save(update_fields=["status"]) 
                                else:
                                    # No live qty -> mark closed locally
                                    trade.status = "closed"
                                    trade.close_reason = trade.close_reason or "market_close"
                                    trade.closed_at = timezone.now()
                                    trade.save(update_fields=["status", "close_reason", "closed_at"]) 
                            except Exception:
                                # Fall back to existing task if direct close fails
                                from core.tasks import close_trade_manually
                                close_trade_manually.delay(trade.id)
                        else:
                            # No credentials -> enqueue existing task (may close locally)
                            from core.tasks import close_trade_manually
                            close_trade_manually.delay(trade.id)
                    except Exception:
                        # If alpaca lib missing, fallback as well
                        from core.tasks import close_trade_manually
                        close_trade_manually.delay(trade.id)
                close_enqueued += 1
            else:
                # Closed/cancelled/failed -> delete
                if dry_run:
                    self.stdout.write(f"Would delete Trade#{trade.id} ({trade.symbol}) with status={status}")
                else:
                    trade.delete()
                deleted += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Reconcile complete. Set FK: {updated_fk}, Close-enqueued: {close_enqueued}, Deleted: {deleted}"
            )
        )


