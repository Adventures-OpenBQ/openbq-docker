# Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Gap-only Coinbase BTC-USD minute history. Never writes to the accepted tape."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time

from app.market_time import naive_utc, wire_time


async def fetch_candles(start, end):
    import httpx
    async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
        response = await client.get(
            'https://api.exchange.coinbase.com/products/BTC-USD/candles',
            params={'granularity': 60, 'start': start.isoformat(), 'end': end.isoformat()},
            headers={'User-Agent': 'OpenBQ-DayChart/1.0'})
        response.raise_for_status()
        if len(response.content) > 256 * 1024:
            raise ValueError('candle response too large')
        return response.json()


def valid_candles(raw):
    result = {}
    for row in raw if isinstance(raw, list) else []:
        try:
            stamp, low, high, opened, close, volume = row
            values = [float(v) for v in (low, high, opened, close, volume)]
            if (not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0
                    or values[4] < 0 or low > min(opened, close) or high < max(opened, close)
                    or int(stamp) != stamp or int(stamp) % 60):
                continue
            result[int(stamp)] = dict(date=wire_time(datetime.fromtimestamp(stamp, timezone.utc)),
                                     low=values[0], high=values[1], open=values[2],
                                     close=values[3], volume=values[4])
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    return result


class BtcBackfill:
    def __init__(self, path, *, fetch=fetch_candles):
        self.path = Path(path)
        self.fetch = fetch
        self.lock = asyncio.Lock()
        self.rows = None
        self.retry_at = 0
        self.rate_lock = asyncio.Lock()
        self.next_request = 0

    def load(self):
        try:
            if self.path.stat().st_size > 2 * 1024 * 1024:
                return {}
            return valid_candles(json.loads(self.path.read_text()))
        except (OSError, ValueError, TypeError):
            return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps([[t, r['low'], r['high'], r['open'], r['close'], r['volume']]
                                        for t, r in sorted(self.rows.items())], allow_nan=False))
        temporary.replace(self.path)

    async def supplement(self, existing, start, end, *, budget=12, now=None):
        if budget <= 0:
            return existing, 0
        try:
            async with asyncio.timeout(budget):
                return await self.fill(existing, start, end, now=now)
        except (TimeoutError, OSError, ValueError):
            return existing, 0

    async def fill(self, existing, start, end, *, now=None):
        now = now or datetime.now(timezone.utc)
        lo = datetime.fromisoformat(str(start)[:10]).replace(tzinfo=timezone.utc)
        hi = min(datetime.fromisoformat(str(end)[:10]).replace(tzinfo=timezone.utc)+timedelta(days=1),
                 now.replace(second=0, microsecond=0))
        if lo < now.replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=5) or hi-lo > timedelta(days=6):
            raise ValueError('backfill window exceeds six UTC days')
        if hi <= lo:
            return existing, 0
        supplied = {int(naive_utc(r['date']).replace(tzinfo=timezone.utc).timestamp()) for r in existing}
        async with self.lock:
            if self.rows is None:
                self.rows = await asyncio.to_thread(self.load)
            floor = int((now-timedelta(days=6)).timestamp())
            self.rows = {t:r for t,r in self.rows.items() if floor <= t < int(hi.timestamp())}
            missing = set(range(int(lo.timestamp()), int(hi.timestamp()), 60))-supplied-self.rows.keys()
            if missing and time.monotonic() >= self.retry_at:
                # At most 36 requests, two in flight, never more than once a minute.
                self.retry_at = time.monotonic()+60
                chunks = sorted({(t-int(lo.timestamp()))//14400 for t in missing})
                limit = asyncio.Semaphore(2)
                async def get(chunk):
                    a = lo+timedelta(minutes=240*chunk)
                    b = min(a+timedelta(minutes=240), hi)
                    async with limit:
                        try:
                            async with self.rate_lock:
                                await asyncio.sleep(max(0, self.next_request-time.monotonic()))
                                self.next_request = time.monotonic()+.15
                            raw = await self.fetch(a,b)
                            rows = {t:r for t,r in valid_candles(raw).items()
                                    if int(a.timestamp()) <= t < int(b.timestamp())}
                            self.rows.update(rows)
                            return rows
                        except Exception:
                            return {}
                try:
                    async with asyncio.timeout(12):
                        results = await asyncio.gather(*(get(chunk) for chunk in chunks))
                except TimeoutError:
                    results = []
                for rows in results:
                    self.rows.update(rows)
                try:
                    await asyncio.to_thread(self.save)
                except OSError:
                    pass  # An unavailable cache must not discard usable history.
            added = [r for t,r in self.rows.items() if int(lo.timestamp()) <= t < int(hi.timestamp()) and t not in supplied]
            return sorted([*existing,*added], key=lambda r: naive_utc(r['date'])), len(added)
