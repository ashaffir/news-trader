import websocket as ws_client

import json

# Replace with your Alpaca API key/secret
API_KEY = "PKX2ME8I45HC3HHOIJ7P"
API_SECRET = "QfPS9B3pQyiJQ3ahSWNgrcIYGLNFaeUVVXWDfNLN"

# Free real-time IEX data feed
# SOCKET = "wss://stream.data.alpaca.markets/v2/iex"
SOCKET = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"


def on_open(ws):
    print("Opened connection")
    auth_data = {"action": "auth", "key": API_KEY, "secret": API_SECRET}
    ws.send(json.dumps(auth_data))

    # Subscribe to crypto trades
    listen_message = {
        "action": "subscribe",
        "trades": ["BTC/USD"],
        "quotes": ["BTC/USD"],
        "bars": ["BTC/USD"],
    }
    ws.send(json.dumps(listen_message))


def on_open(ws):
    print("Opened connection")
    auth_data = {"action": "auth", "key": API_KEY, "secret": API_SECRET}
    ws.send(json.dumps(auth_data))

    # Subscribe to trades for BTC
    listen_message = {
        "action": "subscribe",
        "trades": ["BTC/USD"],
        "quotes": ["BTC/USD"],
        "bars": ["BTC/USD"],
    }

    # Subscribe to trades for AAPL
    #    listen_message = {
    #        "action": "subscribe",
    #        "trades": ["AAPL"],  # real-time trades
    #        "quotes": ["AAPL"],  # real-time quotes
    #        "bars": ["AAPL"]     # real-time 1-min bars
    #    }
    ws.send(json.dumps(listen_message))


def on_message(ws, message):
    data = json.loads(message)
    for msg in data:
        if msg.get("T") == "b":  # bar event
            print(json.dumps(msg, indent=2))


# def on_message(ws, message):
#     data = json.loads(message)
#     print(json.dumps(data, indent=2))

#     for msg in data:
#         if msg.get("T") == "t":  # trade
#             print(f"TRADE {msg['S']} price={msg['p']} size={msg['s']} time={msg['t']}")
#         elif msg.get("T") == "q":  # quote
#             print(f"QUOTE {msg['S']} bid={msg['bp']} ask={msg['ap']} time={msg['t']}")


def on_close(ws, close_status_code, close_msg):
    print("Closed connection")


if __name__ == "__main__":
    ws = ws_client.WebSocketApp(
        SOCKET, on_open=on_open, on_message=on_message, on_close=on_close
    )
    ws.run_forever()
