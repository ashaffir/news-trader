import time
import requests
from dotenv import load_dotenv
import os
load_dotenv()

API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
BASE_URL = os.getenv('ALPACA_API_URL')

HEADERS = {
    'APCA-API-KEY-ID': API_KEY,
    'APCA-API-SECRET-KEY': SECRET_KEY
}

def cancel_all_open_orders():
    r = requests.get(f'{BASE_URL}/orders?status=open', headers=HEADERS)
    r.raise_for_status()
    orders = r.json()

    for order in orders:
        oid = order['id']
        symbol = order['symbol']
        print(f'Cancelling open order for {symbol}')
        cancel_r = requests.delete(f'{BASE_URL}/v2/orders/{oid}', headers=HEADERS)
        if cancel_r.status_code == 204:
            print(f'Cancelled {symbol}')
        else:
            print(f'Failed to cancel {symbol}: {cancel_r.text}')

def get_open_positions():
    r = requests.get(f'{BASE_URL}/positions', headers=HEADERS)
    r.raise_for_status()
    return r.json()

def close_position(symbol):
    print(f'Closing {symbol}...')
    r = requests.delete(f'{BASE_URL}/positions/{symbol}', headers=HEADERS)
    if r.status_code == 200:
        print(f'Successfully submitted close for {symbol}')
    else:
        print(f'Failed to close {symbol}: {r.text}')

def main():
    cancel_all_open_orders()
    time.sleep(1)
    positions = get_open_positions()
    if not positions:
        print("No open positions.")
        return

    for p in positions:
        symbol = p['symbol']
        close_position(symbol)

if __name__ == "__main__":
    main()

