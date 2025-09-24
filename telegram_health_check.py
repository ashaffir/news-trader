#!/usr/bin/env python3
"""
Simple health check script for the Telegram bot container.

This validates health WITHOUT relying on in-process globals by:
- Checking that TELEGRAM_BOT_TOKEN exists
- Calling Telegram Bot API getMe with a short timeout

Exit code 0 = healthy, non-zero = unhealthy.

Usage:
    python telegram_health_check.py
"""

import os
import sys
import logging
from typing import Optional

import httpx

# Suppress verbose logging for health checks
logging.getLogger('httpx').setLevel(logging.WARNING)


def get_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value:
        value = value.strip()
    return value or None


def check_bot_health_sync() -> bool:
    """Check bot health by performing a lightweight Telegram API call."""
    token = get_env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN is not set")
        return False

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, read=8.0, connect=6.0)) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                print(f"❌ Telegram API HTTP {resp.status_code}")
                return False
            data = resp.json()
            if data.get("ok"):
                username = (data.get("result") or {}).get("username", "?")
                print(f"✅ Bot is healthy: @{username}")
                return True
            print(f"❌ Telegram API returned error: {data}")
            return False
    except httpx.RequestError as e:
        print(f"❌ Network error contacting Telegram API: {type(e).__name__}: {e}")
        return False
    except Exception as e:
        print(f"❌ Health check error: {type(e).__name__}: {e}")
        return False


def main() -> int:
    return 0 if check_bot_health_sync() else 1


if __name__ == "__main__":
    sys.exit(main())
