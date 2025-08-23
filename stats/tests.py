from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from core.models import Trade


@override_settings(ROOT_URLCONF='news_trader.urls')
class StatsAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='u', password='p')
        self.client.login(username='u', password='p')

    def test_summary_commission_adjusted(self):
        now = timezone.now()
        t1 = Trade.objects.create(symbol='AAPL', direction='buy', quantity=1, entry_price=100, status='closed', realized_pnl=50.0, commission=5.0, created_at=now - timedelta(days=2), opened_at=now - timedelta(days=2), closed_at=now - timedelta(days=2))
        t2 = Trade.objects.create(symbol='AAPL', direction='sell', quantity=1, entry_price=110, status='closed', realized_pnl=-20.0, commission=2.0, created_at=now - timedelta(days=1), opened_at=now - timedelta(days=1), closed_at=now - timedelta(days=1))
        resp = self.client.get('/stats/api/summary')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Commission-adjusted total: 50-5 + (-20-2) = 23
        self.assertAlmostEqual(data['total_pnl_adjusted'], 23.0, places=3)
        self.assertEqual(data['total_trades'], 2)

    def test_equity_and_daily(self):
        now = timezone.now()
        Trade.objects.create(symbol='MSFT', direction='buy', quantity=1, entry_price=100, status='closed', realized_pnl=10.0, commission=1.0, created_at=now - timedelta(days=2), opened_at=now - timedelta(days=2), closed_at=now - timedelta(days=2))
        Trade.objects.create(symbol='MSFT', direction='buy', quantity=1, entry_price=100, status='closed', realized_pnl=-5.0, commission=1.0, created_at=now - timedelta(days=1), opened_at=now - timedelta(days=1), closed_at=now - timedelta(days=1))
        eq = self.client.get('/stats/api/equity').json()
        self.assertEqual(len(eq['labels']), 2)
        daily = self.client.get('/stats/api/pnl-by-day').json()
        self.assertEqual(len(daily['labels']), 2)


# Create your tests here.
