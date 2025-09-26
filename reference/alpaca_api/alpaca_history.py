from datetime import datetime, timedelta, timezone

from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

# Replace with your Alpaca API keys
API_KEY = "PKX2ME8I45HC3HHOIJ7P"
API_SECRET = "QfPS9B3pQyiJQ3ahSWNgrcIYGLNFaeUVVXWDfNLN"

client = StockHistoricalDataClient(API_KEY, API_SECRET)

# Last 1 hour window (UTC)
end = datetime.now(timezone.utc)
start = end - timedelta(hours=1)

request_params = StockBarsRequest(
    symbol_or_symbols=["NVDA"],
    timeframe=TimeFrame.Minute,
    start=start,
    end=end,
    feed=DataFeed.IEX,  # 👈 force IEX instead of SIP
)

bars = client.get_stock_bars(request_params)

# Convert to DataFrame
df = bars.df.reset_index()

if df.empty:
    print("No data returned for NVDA in the last hour (maybe market closed?)")
else:
    df = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]
    df.to_csv("nvda_last_hour.csv", index=False)
    print("Saved nvda_last_hour.csv")

    # Save to CSV
    df.to_csv("nvda_last_hour.csv", index=False)
    print("Saved nvda_last_hour.csv")
