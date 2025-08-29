from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from core.models import Trade, TradingConfig, Analysis, Post, Source


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

    def test_analysis_endpoints_basic_shapes(self):
        now = timezone.now()
        src = Source.objects.create(name='S', url='https://ex.com/s')
        # Two posts and analyses with different confidences
        p1 = Post.objects.create(source=src, content='c1', url='https://ex.com/p1', created_at=now)
        a1 = Analysis.objects.create(post=p1, symbol='AAPL', direction='buy', confidence=0.85, reason='r')
        t1 = Trade.objects.create(symbol='AAPL', analysis=a1, direction='buy', quantity=1, entry_price=100, status='closed', realized_pnl=10.0, commission=1.0, created_at=now, opened_at=now, closed_at=now)
        p2 = Post.objects.create(source=src, content='c2', url='https://ex.com/p2', created_at=now)
        a2 = Analysis.objects.create(post=p2, symbol='MSFT', direction='sell', confidence=0.65, reason='r')
        t2 = Trade.objects.create(symbol='MSFT', analysis=a2, direction='sell', quantity=1, entry_price=100, status='closed', realized_pnl=-5.0, commission=1.0, created_at=now, opened_at=now, closed_at=now)

        # Confidence distribution
        cd = self.client.get('/stats/api/analysis/confidence-distribution').json()
        self.assertIn('bins', cd)
        self.assertIn('all_counts', cd)
        self.assertEqual(len(cd['bins']), 5)

        # Calibration
        cal = self.client.get('/stats/api/analysis/calibration').json()
        self.assertIn('win_rate', cal)
        self.assertEqual(len(cal['win_rate']), 5)

        # Confidence PnL buckets
        cp = self.client.get('/stats/api/analysis/confidence-pnl-buckets').json()
        self.assertIn('avg_pnl', cp)
        self.assertEqual(len(cp['avg_pnl']), 5)

        # Threshold simulation default
        sim = self.client.get('/stats/api/analysis/threshold-simulation').json()
        self.assertIn('trades', sim)
        self.assertEqual(sim['trades'], 2)

        # Apply min_confidence filter to include only a1
        sim2 = self.client.get('/stats/api/analysis/threshold-simulation?min_confidence=0.8').json()
        self.assertEqual(sim2['trades'], 1)

        # Scatter endpoints
        scatter1 = self.client.get('/stats/api/analysis/confidence-pnl-scatter').json()
        self.assertIn('points', scatter1)
        scatter2 = self.client.get('/stats/api/analysis/duration-pnl-scatter').json()
        self.assertIn('points', scatter2)

    def test_navbar_bot_badge_reflects_state(self):
        """Stats page should receive bot_enabled for navbar indicator."""
        # Bot disabled
        TradingConfig.objects.update_or_create(
            is_active=True,
            defaults={
                'name': 'Default',
                'bot_enabled': False,
                'trading_enabled': True,
            }
        )
        resp = self.client.get(reverse('stats_page'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'BOT DISABLED')

        # Bot enabled
        cfg = TradingConfig.objects.get(is_active=True)
        cfg.bot_enabled = True
        cfg.save(update_fields=['bot_enabled'])
        resp = self.client.get(reverse('stats_page'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'BOT RUNNING')


# Create your tests here.
