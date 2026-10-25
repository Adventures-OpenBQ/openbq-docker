# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Bounded schedule interchange, also consumable by future retained providers.

Bundles are built for whole calendar years and cached as JSON bytes under one byte budget
(review I5): a request whose `start` moves by a day reuses the year it falls in instead of
generating and holding another multi-year bundle. The answer can therefore cover more than
was asked; the client accepts that, since a bundle's own coverage is what its operations
check. Capabilities are read from the generated catalogue, once, in a worker thread, never on
the event loop.
"""

import asyncio
from collections import OrderedDict
from datetime import date, datetime, timezone
from functools import lru_cache
import json
import threading
from starlette.responses import JSONResponse, Response
from openbq_calendar.contracts import MAX_DAYS
from openbq_calendar.registry import CALENDARS, ENTRIES, bounds, resolve_calendar
from openbq_calendar.supplier import generate_bundle

MAX_BYTES = 16 * 1024 * 1024
# ponytail: one process-wide budget (about four 20-year bundles); per-calendar budgets if a deployment needs more.
CACHE_BYTES = 64 * 1024 * 1024
_cache: OrderedDict = OrderedDict()
_cache_bytes = 0
_lock = threading.Lock()


def clear_cache():
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0


def cached_bytes():
    return _cache_bytes


def cached_entries():
    return len(_cache)


def build_bundle(calendar_id, start_year, end_year):
    """One whole-year bundle as JSON bytes, from the cache when it holds it."""
    global _cache_bytes
    key = ("exchange:" + resolve_calendar(calendar_id), start_year, end_year)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    # Whole years, clipped to the calendar's bounds: XSHG's first year starts 1990-12-03, XSES's last ends 2026-12-31.
    low, high = bounds(key[0].removeprefix("exchange:"))
    body = generate_bundle(
        key[0],
        max(date(start_year, 1, 1), low),
        min(date(end_year, 12, 31), high),
        generated_at=datetime.now(timezone.utc),
    )
    raw = json.dumps(body, separators=(",", ":")).encode()
    with _lock:
        if key not in _cache and len(raw) <= CACHE_BYTES:
            _cache[key] = raw
            _cache_bytes += len(raw)
            while _cache_bytes > CACHE_BYTES:
                _, old = _cache.popitem(last=False)
                _cache_bytes -= len(old)
    return raw


def _entry(name):
    start, end = bounds(name)
    return {
        "calendarId": "exchange:" + name,
        "name": name,
        "timezone": ENTRIES[name]["timezone"],
        "kind": "exchange_trading",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "policies": ["operational-v1", "planning-v1"],
        "aliases": [{"alias": name, "calendarId": "exchange:" + name}],
    }


@lru_cache(maxsize=1)
def _capabilities():
    return {
        "schemaVersion": 1,
        "providerId": "openbq-calendar/0.1.0",
        "calendars": [_entry(name) for name in CALENDARS],
        "limits": {"members": 8, "days": 366 * 20, "steps": 10000, "expressions": 100, "bytes": MAX_BYTES},
    }


async def capabilities():
    return await asyncio.to_thread(_capabilities)


async def bundle(calendar_id: str, start: str, end: str):
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last:
            raise ValueError("start must not follow end")
        # Ruling RF2: the whole-year coverage this would build must fit the contract's span, checked before building.
        if (date(last.year, 12, 31) - date(first.year, 1, 1)).days >= MAX_DAYS:
            return JSONResponse(
                {"error": {"code": "RESOURCE_LIMIT", "message": f"span exceeds {MAX_DAYS} days"}}, status_code=413
            )
        raw = await asyncio.to_thread(build_bundle, calendar_id, first.year, last.year)
    except (ValueError, KeyError, OverflowError) as e:
        return JSONResponse({"error": {"code": "CALENDAR_UNAVAILABLE", "message": str(e)[:256]}}, status_code=422)
    if len(raw) > MAX_BYTES:
        return JSONResponse({"error": {"code": "RESOURCE_LIMIT"}}, status_code=413)
    return Response(raw, media_type="application/json")


def register(router):
    router.api_router.get("/trading/v1/calendars", openapi_extra={"widget_config": {"exclude": True}})(capabilities)
    router.api_router.get("/trading/v1/bundle", openapi_extra={"widget_config": {"exclude": True}})(bundle)
