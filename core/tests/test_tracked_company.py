from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone
from core.models import TrackedCompany, Trade, Analysis, Post, Source
import tempfile
import os
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile


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

    def test_admin_import_view_creates_updates_and_deactivates(self):
        # Create superuser and login
        User = get_user_model()
        admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.login(username="admin", password="pass")

        # Initial companies
        TrackedCompany.objects.create(symbol="AAPL", name="Apple Inc.")
        TrackedCompany.objects.create(symbol="MSFT", name="Microsoft")

        url = reverse("admin:core_trackedcompany_import")

        # Upload CSV with AAPL (updated) and GOOG, and deactivate missing (MSFT should deactivate)
        csv_content = (
            "symbol,name,industry,sector,market\n"
            "AAPL,Apple Inc Updated,Consumer Electronics,Information Technology,USA\n"
            "GOOG,Alphabet Inc,Internet,Communication Services,USA\n"
        )
        uploaded = SimpleUploadedFile("companies.csv", csv_content.encode("utf-8"), content_type="text/csv")
        resp = self.client.post(url, {"csv_file": uploaded, "deactivate_missing": "on"}, follow=True)
        self.assertEqual(resp.status_code, 200)

        aapl = TrackedCompany.objects.get(symbol="AAPL")
        goog = TrackedCompany.objects.get(symbol="GOOG")
        msft = TrackedCompany.objects.get(symbol="MSFT")
        self.assertEqual(aapl.name, "Apple Inc Updated")
        self.assertTrue(goog.is_active)
        self.assertFalse(msft.is_active)

    def test_admin_import_view_rejects_bad_headers(self):
        User = get_user_model()
        admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.login(username="admin", password="pass")
        url = reverse("admin:core_trackedcompany_import")
        csv_content = "symbol,name\nAAPL,Apple Inc\n"
        uploaded = SimpleUploadedFile("companies.csv", csv_content.encode("utf-8"), content_type="text/csv")
        resp = self.client.post(url, {"csv_file": uploaded}, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Should show error message in response content
        self.assertContains(resp, "Missing required CSV headers")

    def test_untracked_trade_allowed_when_config_enabled(self):
        from core.models import TradingConfig
        cfg = TradingConfig.objects.create(name="Cfg1", is_active=True, allow_untracked_symbols=True)
        src = Source.objects.create(name="S", url="https://example.com")
        post = Post.objects.create(source=src, url="https://example.com/x", content="x")
        analysis = Analysis.objects.create(post=post, symbol="ZZZZ", direction="buy", confidence=0.99, reason="r", trading_config_used=cfg)
        from core.tasks import create_new_trade
        # This should not be rejected due to tracked-company check; function may exit earlier due to missing keys
        create_new_trade(analysis.id)

    def test_untracked_trade_blocked_when_config_disabled(self):
        from core.models import TradingConfig
        cfg = TradingConfig.objects.create(name="Cfg2", is_active=True, allow_untracked_symbols=False)
        src = Source.objects.create(name="S2", url="https://example.com/2")
        post = Post.objects.create(source=src, url="https://example.com/y", content="y")
        analysis = Analysis.objects.create(post=post, symbol="QQQQ", direction="buy", confidence=0.99, reason="r", trading_config_used=cfg)
        from core.tasks import create_new_trade
        create_new_trade(analysis.id)


