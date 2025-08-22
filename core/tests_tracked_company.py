from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone
from core.models import TrackedCompany, Trade, Analysis, Post, Source
import tempfile
import os


class TrackedCompanyTests(TestCase):
    def test_model_str_and_defaults(self):
        company = TrackedCompany.objects.create(
            symbol="AAPL", name="Apple Inc.", sector="Information Technology", industry="Consumer Electronics", market="USA"
        )
        self.assertEqual(str(company), "AAPL - Apple Inc.")
        self.assertTrue(company.is_active)
        self.assertIsNotNone(company.created_at)
        self.assertIsNotNone(company.updated_at)

    def test_import_command_creates_and_updates(self):
        # Prepare a temporary CSV
        csv_content_v1 = """symbol,name,industry,sector,market
AAPL,Apple Inc.,Consumer Electronics,Information Technology,USA
MSFT,Microsoft Corporation,Software,Information Technology,USA
"""
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as tmp:
            tmp.write(csv_content_v1)
            tmp.flush()
            path = tmp.name

        try:
            # Run import
            call_command("import_tracked_companies", path, verbosity=0)

            # Validate creations
            self.assertTrue(TrackedCompany.objects.filter(symbol="AAPL").exists())
            self.assertTrue(TrackedCompany.objects.filter(symbol="MSFT").exists())
            aapl = TrackedCompany.objects.get(symbol="AAPL")
            self.assertTrue(aapl.is_active)
            self.assertEqual(aapl.name, "Apple Inc.")

            # Update CSV to change a name and re-import
            csv_content_v2 = """symbol,name,industry,sector,market
AAPL,Apple Inc (Updated),Consumer Electronics,Information Technology,USA
"""
            with open(path, "w") as tmp2:
                tmp2.write(csv_content_v2)

            call_command("import_tracked_companies", path, verbosity=0)
            aapl.refresh_from_db()
            self.assertEqual(aapl.name, "Apple Inc (Updated)")

        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def test_reconcile_trades_command_maps_fk_and_enqueues_close(self):
        # Setup tracked companies and a trade without FK
        tc = TrackedCompany.objects.create(symbol="AAPL", name="Apple Inc.")
        source = Source.objects.create(name="X", url="https://example.com/x")
        post = Post.objects.create(source=source, content="c", url="https://e/x")
        analysis = Analysis.objects.create(post=post, symbol="AAPL", direction="buy", confidence=0.9, reason="r")
        trade = Trade.objects.create(analysis=analysis, symbol="AAPL", direction="buy", quantity=1, entry_price=10.0, status="open")
        self.assertIsNone(trade.tracked_company)

        # Dry run first
        call_command("reconcile_trades_tracked_companies", "--dry-run", verbosity=0)
        trade.refresh_from_db()
        # Dry run should not have set FK
        self.assertIsNone(trade.tracked_company)

        # Real run: should set FK and enqueue close for open trade; we cannot assert celery, but FK should be set.
        call_command("reconcile_trades_tracked_companies", verbosity=0)
        trade.refresh_from_db()
        self.assertEqual(trade.tracked_company_id, tc.id)


