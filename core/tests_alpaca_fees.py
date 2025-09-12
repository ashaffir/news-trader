"""
Tests for Alpaca fee ingestion functionality.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from core.models import Trade, TrackedCompany
from core.utils.alpaca_fees import fetch_trade_fees, _calculate_estimated_fees


class AlpacaFeesTestCase(TestCase):
    def setUp(self):
        """Set up test data."""
        self.company, _ = TrackedCompany.objects.get_or_create(
            symbol="AAPL", 
            defaults={"name": "Apple Inc."}
        )
        
        self.trade = Trade.objects.create(
            symbol="AAPL",
            tracked_company=self.company,
            direction="buy",
            quantity=100,
            entry_price=150.0,
            status="open"
        )
        
    def test_calculate_estimated_fees(self):
        """Test the estimated fee calculation function."""
        # Test TAF fee calculation for 100 shares
        fees = _calculate_estimated_fees(100, "buy")
        expected_taf = min(100 * 0.000166, 8.30)  # Should be 0.0166
        self.assertAlmostEqual(fees, expected_taf, places=4)
        
        # Test with large quantity that hits the TAF cap
        fees = _calculate_estimated_fees(100000, "sell")
        self.assertEqual(fees, 8.30)  # Should hit the TAF cap
        
    @patch('core.utils.alpaca_fees.get_alpaca_api_client')
    def test_fetch_trade_fees_no_api(self, mock_get_client):
        """Test fee fetching when API client is not available."""
        mock_get_client.return_value = None
        
        fees = fetch_trade_fees(
            symbol="AAPL",
            trade_time=timezone.now(),
            quantity=100,
            side="buy"
        )
        
        # Should return 0 when API is not available
        self.assertEqual(fees, 0.0)
        
    @patch('core.utils.alpaca_fees.get_alpaca_api_client')
    def test_fetch_trade_fees_with_activities(self, mock_get_client):
        """Test fee fetching when API returns fee activities."""
        # Mock API client
        mock_api = MagicMock()
        mock_get_client.return_value = mock_api
        
        # Mock fee activity
        mock_activity = MagicMock()
        mock_activity.symbol = "AAPL"
        mock_activity.qty = 100
        mock_activity.side = "buy"
        mock_activity.fee = -0.50  # Fees are typically negative
        mock_activity.date = timezone.now().isoformat()
        
        mock_api.get_activities.return_value = [mock_activity]
        
        fees = fetch_trade_fees(
            symbol="AAPL",
            trade_time=timezone.now(),
            quantity=100,
            side="buy"
        )
        
        self.assertEqual(fees, 0.50)  # Should return absolute value of fee
        
    @patch('core.utils.alpaca_fees.get_alpaca_api_client')
    def test_fetch_trade_fees_fallback_to_estimated(self, mock_get_client):
        """Test fee fetching falls back to estimated fees when API fails."""
        # Mock API client that raises an exception
        mock_api = MagicMock()
        mock_api.get_activities.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_api
        
        fees = fetch_trade_fees(
            symbol="AAPL",
            trade_time=timezone.now(),
            quantity=100,
            side="buy"
        )
        
        # Should return estimated TAF fee
        expected_taf = min(100 * 0.000166, 8.30)
        self.assertAlmostEqual(fees, expected_taf, places=4)
        
    def test_get_alpaca_api_client_no_credentials(self):
        """Test API client creation when credentials are missing."""
        with patch.dict(os.environ, {}, clear=True):
            from core.utils.alpaca_fees import get_alpaca_api_client
            client = get_alpaca_api_client()
            self.assertIsNone(client)
            
    @patch.dict(os.environ, {
        'ALPACA_API_KEY': 'test_key',
        'ALPACA_SECRET_KEY': 'test_secret'
    })
    def test_get_alpaca_api_client_success(self):
        """Test successful API client creation."""
        with patch('alpaca_trade_api.REST') as mock_tradeapi:
            from core.utils.alpaca_fees import get_alpaca_api_client
            
            mock_client = MagicMock()
            mock_tradeapi.return_value = mock_client
            
            client = get_alpaca_api_client()
            
            self.assertEqual(client, mock_client)
            mock_tradeapi.assert_called_once_with(
                'test_key', 
                'test_secret', 
                base_url='https://paper-api.alpaca.markets'
            )


class TradeClosingWithFeesTestCase(TestCase):
    def setUp(self):
        """Set up test data for trade closing tests."""
        self.company, _ = TrackedCompany.objects.get_or_create(
            symbol="TSLA", 
            defaults={"name": "Tesla Inc."}
        )
        
    @patch('core.utils.alpaca_fees.fetch_trade_fees')
    def test_trade_close_with_fees(self, mock_fetch_fees):
        """Test that fees are properly calculated and stored when closing a trade."""
        mock_fetch_fees.return_value = 1.25  # Mock fee amount
        
        trade = Trade.objects.create(
            symbol="TSLA",
            tracked_company=self.company,
            direction="buy",
            quantity=100,
            entry_price=200.0,
            status="open",
            opened_at=timezone.now()
        )
        
        # Simulate closing the trade (this would normally be done via views or tasks)
        exit_price = 210.0
        pnl = (exit_price - trade.entry_price) * trade.quantity  # $1000
        
        trade.status = "closed"
        trade.exit_price = exit_price
        trade.realized_pnl = pnl
        trade.commission = mock_fetch_fees.return_value
        trade.closed_at = timezone.now()
        trade.save()
        
        # Verify the trade was updated correctly
        trade.refresh_from_db()
        self.assertEqual(trade.status, "closed")
        self.assertEqual(trade.exit_price, 210.0)
        self.assertEqual(trade.realized_pnl, 1000.0)
        self.assertEqual(trade.commission, 1.25)
        
        # Verify that the stats calculation would be correct
        from stats.api import _commission_adjusted_realized_pnl
        net_pnl = _commission_adjusted_realized_pnl(trade)
        self.assertEqual(net_pnl, 998.75)  # $1000 - $1.25 = $998.75
