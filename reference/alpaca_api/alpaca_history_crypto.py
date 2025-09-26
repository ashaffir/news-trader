from datetime import datetime, timedelta, timezone
import pandas as pd

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# Replace with your Alpaca API keys
API_KEY = "PKX2ME8I45HC3HHOIJ7P"
API_SECRET = "QfPS9B3pQyiJQ3ahSWNgrcIYGLNFaeUVVXWDfNLN"

client = CryptoHistoricalDataClient(API_KEY, API_SECRET)

# Last 1 hour window (UTC)
end = datetime.now(timezone.utc)
start = end - timedelta(hours=1)

request_params = CryptoBarsRequest(
    symbol_or_symbols=["BTC/USD"], timeframe=TimeFrame.Minute, start=start, end=end
)

bars = client.get_crypto_bars(request_params)

# Convert to DataFrame
df = bars.df.reset_index()

if df.empty:
    print("No crypto data returned for BTC/USD in the last hour")
else:
    df = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]
    df.to_csv("btc_last_hour.csv", index=False)
    print("Saved btc_last_hour.csv")
