# Alpaca Fee Ingestion Implementation

## Overview
This implementation adds automatic ingestion of Alpaca fees and commissions when trades are closed, ensuring that PnL calculations reflect net values after fees.

## Files Modified

### 1. New Utility Module: `core/utils/alpaca_fees.py`
- **Purpose**: Centralized fee fetching and calculation
- **Key Functions**:
  - `fetch_trade_fees()`: Fetches actual fees from Alpaca API for a specific trade
  - `_calculate_estimated_fees()`: Fallback fee calculation based on Alpaca's fee schedule
  - `get_alpaca_api_client()`: Helper to create Alpaca API client
  - `fetch_fees_for_trade_period()`: Debug utility for detailed fee analysis

### 2. Trade Close Logic Updates: `core/views.py`
- **Location**: Manual trade close endpoint (~line 1345-1367)
- **Changes**: Added fee fetching and assignment to `trade.commission` field
- **Impact**: Manual trade closes now include commission data

### 3. Trade Close Logic Updates: `core/tasks.py`
- **Locations**: Multiple trade close scenarios
  - Manual close via Alpaca API (~line 2882-2905)
  - Fallback close with market price (~line 2926-2949)  
  - Local close without API (~line 2955, 2966)
  - Position disappeared close (~line 3287-3309)
- **Changes**: Added fee fetching where API is available, set commission to 0.0 for local closes
- **Impact**: All automated trade closes now include commission data

### 4. Test Suite: `core/tests_alpaca_fees.py`
- **Purpose**: Comprehensive testing of fee functionality
- **Coverage**: 
  - Fee calculation accuracy
  - API client creation and error handling
  - Fee fetching with various API responses
  - Integration with trade closing logic
  - Commission-adjusted PnL calculations

## Fee Calculation Logic

### Primary Method: Alpaca API Activities
1. Query Alpaca's `/v2/account/activities` endpoint for fee activities
2. Match activities by symbol, quantity, side, and time window
3. Sum all fees for the specific trade

### Fallback Method: Estimated Fees
When API is unavailable or returns no data:
- **FINRA TAF**: $0.000166 per share (max $8.30 per trade)
- **SEC fees**: $0 for most retail trades (negligible)

## Integration with Existing Stats

The existing stats module (`stats/api.py`) already has commission-adjusted PnL calculations:
```python
def _commission_adjusted_realized_pnl(trade: Trade) -> float:
    realized = float(trade.realized_pnl or 0.0)
    commission = float(trade.commission or 0.0)
    return realized - commission
```

Now that the `commission` field is populated, all stats will automatically show net PnL.

## Error Handling

- **Graceful Degradation**: If fee fetching fails, defaults to estimated fees
- **Logging**: All fee fetching attempts and errors are logged
- **No Blocking**: Fee calculation errors never prevent trade closure
- **Backwards Compatible**: Existing trades with commission=0.0 continue to work

## Configuration

The implementation uses existing Alpaca API configuration:
- `ALPACA_API_KEY`: API key for Alpaca account
- `ALPACA_SECRET_KEY`: Secret key for Alpaca account  
- `ALPACA_BASE_URL`: Base URL (defaults to paper trading)

## Testing

Run tests with:
```bash
python manage.py test core.tests_alpaca_fees --settings=news_trader.test_settings
```

All tests pass, covering:
- Fee calculation accuracy
- API error handling
- Integration scenarios
- Commission-adjusted PnL verification

## Result

- **Before**: PnL calculations showed gross profits/losses
- **After**: PnL calculations automatically show net profits/losses after Alpaca fees
- **Compliance**: System now properly accounts for fees per Alpaca's Broker Fee Schedule
- **Transparency**: Fees are stored separately in `Trade.commission` field for audit trails
