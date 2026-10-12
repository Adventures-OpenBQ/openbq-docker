#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Connect to the real EODHD crypto websocket for ~12s and verify ticks arrive.

Crypto trades 24/7, so this is runnable at any hour. Usage:

    EODHD_DEMO_WS_KEY=<EODHD's public demo ws key> .venv/bin/python scripts/smoke.py
    EODHD_API_KEY=<your token> .venv/bin/python scripts/smoke.py

openbq-docker commits no key value, not even EODHD's public demo key (key hygiene,
as in docs/v9/eodhd-port.md): take the demo websocket key from EODHD's own docs.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.feeds import FeedManager  # noqa: E402
from app.quotes import QuoteTable  # noqa: E402

# EODHD's PUBLIC demo websocket key (from their docs and the official SDK's own
# demo code). Serves exactly the demo symbol set: AAPL, MSFT, TSLA / BTC-USD,
# ETH-USD / EURUSD. NOTE: the REST-only "demo" token does NOT work here — the
# SDK's WebSocketClient rejects it on key-format validation. openbq-docker reads
# it from the environment instead of committing it.
DEMO_WS_KEY = os.environ.get("EODHD_DEMO_WS_KEY", "").strip()

SYMBOLS = ["BTC-USD", "ETH-USD"]


async def main() -> int:
    key = os.environ.get("EODHD_API_KEY", "").strip() or DEMO_WS_KEY
    if not key:
        print("SKIP: no key (set EODHD_API_KEY, or EODHD_DEMO_WS_KEY to EODHD's public demo ws key)")
        return 2
    quotes = QuoteTable()
    manager = FeedManager(key, quotes, rebuild_delay=0.0)
    task = asyncio.create_task(manager.run())
    manager.register("smoke", SYMBOLS)
    await asyncio.sleep(12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    ticked = sorted(s for s, r in quotes.rows.items() if r["price"] is not None)
    for sym in SYMBOLS:
        row = quotes.rows.get(sym)
        print(f"  {sym:8} {row}")
    print(f"{len(ticked)}/{len(SYMBOLS)} symbols ticked: {ticked}")
    return 0 if ticked else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
