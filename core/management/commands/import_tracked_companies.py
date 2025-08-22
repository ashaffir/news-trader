import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import TrackedCompany


class Command(BaseCommand):
    help = "Import tracked companies from the provided CSV file."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            nargs="?",
            default=str(Path.cwd() / "full_top_traded_companies_by_industry_expanded_with_financials.csv"),
            help="Path to the CSV file (defaults to project root CSV)",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Deactivate companies not present in the CSV",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"]).expanduser()
        if not csv_path.exists():
            raise CommandError(f"CSV file not found: {csv_path}")

        created = 0
        updated = 0
        seen_symbols = set()

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_headers = {"symbol", "name", "industry", "sector", "market"}
            missing = required_headers - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"Missing required CSV headers: {', '.join(sorted(missing))}")

            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                seen_symbols.add(symbol)
                defaults = {
                    "name": (row.get("name") or "").strip(),
                    "industry": (row.get("industry") or "").strip(),
                    "sector": (row.get("sector") or "").strip(),
                    "market": (row.get("market") or "").strip(),
                    "is_active": True,
                }
                obj, was_created = TrackedCompany.objects.update_or_create(
                    symbol=symbol, defaults=defaults
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        deactivated = 0
        if bool(options.get("deactivate_missing")):
            # Deactivate any companies not found in this import run
            deactivated = (
                TrackedCompany.objects.exclude(symbol__in=seen_symbols)
                .filter(is_active=True)
                .update(is_active=False)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. Created: {created}, Updated: {updated}, Deactivated: {deactivated}"
            )
        )


