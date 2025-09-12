"""
Utility functions for fetching and calculating fees from Alpaca API.

This module provides functionality to retrieve fee information from Alpaca's
account activities API and calculate the total fees associated with a trade.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_alpaca_api_client():
    """Get configured Alpaca API client."""
    try:
        import alpaca_trade_api as tradeapi
        
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        if not api_key or not secret_key:
            logger.error("Alpaca API credentials not found")
            return None
            
        return tradeapi.REST(api_key, secret_key, base_url=base_url)
    except ImportError:
        logger.error("alpaca-trade-api package not installed")
        return None
    except Exception as e:
        logger.error(f"Error creating Alpaca API client: {e}")
        return None


def fetch_trade_fees(symbol: str, trade_time: datetime, quantity: float, side: str) -> float:
    """
    Fetch and calculate fees associated with a specific trade.
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL')
        trade_time: Time when the trade was executed
        quantity: Number of shares traded
        side: 'buy' or 'sell'
    
    Returns:
        Total fees for the trade in dollars
    """
    api = get_alpaca_api_client()
    if not api:
        logger.warning("Cannot fetch fees: Alpaca API client not available")
        return 0.0
    
    try:
        # Convert Django timezone-aware datetime to naive UTC for API
        if timezone.is_aware(trade_time):
            trade_time_utc = trade_time.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            trade_time_utc = trade_time
            
        # Define time window around the trade (±5 minutes for matching)
        start_time = trade_time_utc - timedelta(minutes=5)
        end_time = trade_time_utc + timedelta(minutes=5)
        
        # Try different method names as the exact API method name may vary
        activities = None
        for method_name in ['get_activities', 'list_activities', 'get_account_activities']:
            if hasattr(api, method_name):
                method = getattr(api, method_name)
                try:
                    # Try to get fee activities for the time period
                    activities = method(
                        activity_type='FEE',
                        date=start_time.strftime('%Y-%m-%d'),
                        until=end_time.strftime('%Y-%m-%d')
                    )
                    logger.info(f"Successfully fetched activities using {method_name}")
                    break
                except Exception as method_error:
                    logger.debug(f"Method {method_name} failed: {method_error}")
                    continue
        
        if activities is None:
            # If no method worked, try a more general approach
            try:
                # Some versions might use different parameter names
                activities = api.get_activities(
                    activity_types=['FEE', 'CFEE', 'REG'],  # Include common fee types
                    page_size=100
                )
                # Filter by date and symbol manually
                if activities:
                    activities = [
                        a for a in activities 
                        if (hasattr(a, 'date') and 
                            start_time <= datetime.fromisoformat(a.date.replace('Z', '+00:00')).replace(tzinfo=None) <= end_time and
                            hasattr(a, 'symbol') and a.symbol == symbol)
                    ]
            except Exception as e:
                logger.warning(f"All activity fetch methods failed: {e}")
                return _calculate_estimated_fees(quantity, side)
        
        # Calculate total fees from activities
        total_fees = 0.0
        if activities:
            for activity in activities:
                try:
                    # Check if this activity is related to our trade
                    activity_symbol = getattr(activity, 'symbol', '')
                    activity_qty = getattr(activity, 'qty', 0)
                    activity_side = getattr(activity, 'side', '')
                    
                    # Match by symbol, quantity (approximately), and side
                    if (activity_symbol == symbol and 
                        abs(float(activity_qty) - abs(quantity)) < 1.0 and  # Allow small quantity differences
                        activity_side.lower() == side.lower()):
                        
                        # Get fee amount (might be in different fields)
                        fee_amount = 0.0
                        for fee_field in ['fee', 'amount', 'net_amount']:
                            if hasattr(activity, fee_field):
                                fee_val = getattr(activity, fee_field)
                                if fee_val and float(fee_val) < 0:  # Fees are typically negative
                                    fee_amount += abs(float(fee_val))
                        
                        total_fees += fee_amount
                        logger.info(f"Found fee activity for {symbol}: ${fee_amount:.4f}")
                        
                except Exception as e:
                    logger.warning(f"Error processing activity: {e}")
                    continue
        
        # If no fees found via API, calculate estimated fees
        if total_fees == 0.0:
            total_fees = _calculate_estimated_fees(quantity, side)
            logger.info(f"No fee activities found for {symbol}, using estimated fees: ${total_fees:.4f}")
        
        return total_fees
        
    except Exception as e:
        logger.error(f"Error fetching trade fees for {symbol}: {e}")
        # Fallback to estimated fees
        return _calculate_estimated_fees(quantity, side)


def _calculate_estimated_fees(quantity: float, side: str) -> float:
    """
    Calculate estimated fees based on Alpaca's fee schedule.
    
    This is a fallback when we can't fetch actual fees from the API.
    Based on the fee schedule:
    - FINRA TAF: $0.000166 per share (max $8.30 per trade)
    - SEC fees: typically very small for sells
    """
    try:
        fees = 0.0
        abs_quantity = abs(float(quantity))
        
        # FINRA Trading Activity Fee (TAF) - applies to all trades
        taf_fee = min(abs_quantity * 0.000166, 8.30)
        fees += taf_fee
        
        # SEC fees for sells (very small, often $0)
        if side.lower() == 'sell':
            # SEC fee is $0.00 per $1,000,000 as of the fee schedule
            # This is effectively $0 for most retail trades
            pass
        
        logger.info(f"Estimated fees for {abs_quantity} shares ({side}): ${fees:.4f}")
        return fees
        
    except Exception as e:
        logger.error(f"Error calculating estimated fees: {e}")
        return 0.0


def fetch_fees_for_trade_period(symbol: str, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
    """
    Fetch all fee activities for a symbol within a time period.
    
    This is useful for debugging or detailed fee analysis.
    """
    api = get_alpaca_api_client()
    if not api:
        return []
    
    try:
        # Convert to UTC naive datetime
        if timezone.is_aware(start_time):
            start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)
        if timezone.is_aware(end_time):
            end_time = end_time.astimezone(timezone.utc).replace(tzinfo=None)
        
        activities = []
        for method_name in ['get_activities', 'list_activities', 'get_account_activities']:
            if hasattr(api, method_name):
                method = getattr(api, method_name)
                try:
                    activities = method(
                        activity_type='FEE',
                        date=start_time.strftime('%Y-%m-%d'),
                        until=end_time.strftime('%Y-%m-%d')
                    )
                    break
                except Exception:
                    continue
        
        fee_activities = []
        for activity in activities or []:
            if getattr(activity, 'symbol', '') == symbol:
                fee_activities.append({
                    'date': getattr(activity, 'date', ''),
                    'symbol': getattr(activity, 'symbol', ''),
                    'qty': getattr(activity, 'qty', 0),
                    'side': getattr(activity, 'side', ''),
                    'fee': getattr(activity, 'fee', 0),
                    'amount': getattr(activity, 'amount', 0),
                })
        
        return fee_activities
        
    except Exception as e:
        logger.error(f"Error fetching fee activities for {symbol}: {e}")
        return []
