from datetime import datetime, timezone, timedelta
import asyncio
import pytest
from app.btc_backfill import BtcBackfill

NOW = datetime(2026, 11, 22, 0, 4, 30, tzinfo=timezone.utc)
BASE = int(NOW.replace(minute=0, second=0).timestamp())
def candle(i, close=100):
    return [BASE+i*60, close-1, close+1, close, close, 2]

async def test_gap_only_completed_minutes_and_durable_cache(tmp_path):
    calls=[]
    async def fetch(lo, hi):
        calls.append((lo,hi))
        return [candle(i) for i in range(6)] + [candle(1,101)]
    cache=BtcBackfill(tmp_path/'cache.json', fetch=fetch)
    existing=[{'date':'2026-11-22T00:02:00Z','close':999}]
    rows,count=await cache.fill(existing,'2026-11-22','2026-11-22',now=NOW)
    assert len(rows)==4 and count==3
    assert rows[2]['close']==999
    assert len(calls)==1
    restarted=BtcBackfill(tmp_path/'cache.json',fetch=fetch)
    assert await restarted.fill(existing,'2026-11-22','2026-11-22',now=NOW)==(rows,count)
    assert len(calls)==1

async def test_failure_cooldown_and_coalescing(tmp_path):
    calls=[]
    async def fail(lo,hi):
        calls.append(lo)
        await asyncio.sleep(.001)
        raise RuntimeError('unavailable')
    cache=BtcBackfill(tmp_path/'cache.json',fetch=fail)
    results=await asyncio.gather(*(cache.fill([], '2026-11-22','2026-11-22',now=NOW) for _ in range(3)))
    assert results==[([],0)]*3 and len(calls)==1

async def test_invalid_rows_and_bounds(tmp_path):
    async def fetch(lo,hi):
        return [candle(-1),candle(0),candle(1,float('nan')),candle(2,-1),
                [BASE+61,1,3,2,2,1],['bad'],candle(4)]
    cache=BtcBackfill(tmp_path/'cache.json',fetch=fetch)
    rows,count=await cache.fill([], '2026-11-22','2026-11-22',now=NOW)
    assert count==1 and len(rows)==1
    with pytest.raises(ValueError):
        await cache.fill([], '2026-11-01','2026-11-22',now=NOW)

async def test_requests_bounded_and_cached_overlap(tmp_path):
    calls=[]
    async def fetch(lo,hi):
        calls.append((lo,hi))
        assert (hi-lo).total_seconds()<=240*60
        return [[t,99,101,100,100,2] for t in range(int(lo.timestamp()),int(hi.timestamp()),60)]
    cache=BtcBackfill(tmp_path/'cache.json',fetch=fetch)
    now=NOW.replace(hour=23,minute=59)
    rows,count=await cache.fill([], '2026-11-22','2026-11-22',now=now)
    assert len(rows)==1439 and count==1439 and len(calls)==6
    await cache.fill([], '2026-11-22','2026-11-22',now=now)
    assert len(calls)==6

async def test_optional_backfill_timeout_preserves_existing(tmp_path):
    async def slow(lo,hi):
        await asyncio.sleep(1)
    cache=BtcBackfill(tmp_path/'cache.json',fetch=slow)
    existing=[{'date':'2026-11-22T00:02:00Z','close':999}]
    assert await cache.supplement(existing,'2026-11-22','2026-11-22',budget=.005,now=NOW)==(existing,0)

async def test_request_starts_are_paced(tmp_path):
    import time
    calls=[]
    async def fetch(lo,hi):
        calls.append(time.monotonic())
        return []
    cache=BtcBackfill(tmp_path/'cache.json',fetch=fetch)
    await cache.fill([], '2026-11-22','2026-11-22',now=NOW.replace(hour=9))
    assert len(calls)==3 and min(b-a for a,b in zip(calls,calls[1:]))>=.14
