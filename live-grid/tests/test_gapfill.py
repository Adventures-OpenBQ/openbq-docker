# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Filling the minutes live-grid was down for (user ruling 2026-10-17: at query time).

A restarted live-grid hears nothing while it is down, so kdb's ticks have a hole.
/series fills minutes that have no tick bar from EODHD: US equities from the
real-time service's recent closed minute bars (the same EDGX stream), crypto
from intraday 1m. Ticks win wherever they exist.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app import gapfill
from app import main as main_mod

T0 = datetime(2026, 10, 16, 14, 0)
MS = lambda dt: int((dt - datetime(1970, 1, 1)).total_seconds() * 1000)


def test_parse_history_normalises_ms_and_ns_and_drops_the_forming_bar():
    raw = [
        {"s": "AAPL", "i": "1m", "t": MS(T0), "o": 1, "h": 2, "l": 1, "c": 2, "v": 5},
        {"s": "AAPL", "i": "1m", "t": MS(T0 + timedelta(minutes=1)) * 10**6,
         "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},
        # the forming bar: stamped with its last trade, not its minute
        {"s": "AAPL", "i": "1m", "t": (MS(T0 + timedelta(minutes=2)) + 19_777) * 10**6,
         "o": 3, "h": 3, "l": 3, "c": 3, "v": 2},
    ]
    rows = gapfill.parse_history(raw)
    assert [r["date"] for r in rows] == [T0, T0 + timedelta(minutes=1)]
    assert rows[0] == {"date": T0, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 5}


def test_parse_history_tolerates_junk():
    assert gapfill.parse_history([{"t": "x"}, None, {"s": "AAPL"}]) == []
    assert gapfill.parse_history({"error": 1}) == []


def _m(minute, close, volume=1):
    return {"date": T0 + timedelta(minutes=minute), "open": close, "high": close,
            "low": close, "close": close, "volume": volume, "vwap": close}


class _Store:
    def tick_span(self, symbol):
        return (T0, T0 + timedelta(minutes=9, seconds=30))


class _Recorder:
    store = _Store()


@pytest.fixture
def wired(monkeypatch):
    """Ticks for minutes 0-2 and 7-9 (live-grid down 3-6); fills for 2-6."""
    seen = {"history": [], "crypto": []}
    tick_minutes = [_m(i, 10) for i in (0, 1, 2, 7, 8, 9)]

    def aggregate(store, sym, interval, lo, hi):
        rows = [r for r in tick_minutes if lo <= r["date"] <= hi]
        return main_mod_resample(rows, interval)

    async def recent(symbol, key):
        seen["history"].append((symbol, key))
        return [_m(i, 20, volume=3) for i in (2, 3, 4, 5, 6)]

    async def fake_series(symbol, interval, start, end, provider="kdb"):
        if interval == "1m" and "-" in symbol:
            seen["crypto"].append((start, end))
            return [{**_m(i, 30), "date": (T0 + timedelta(minutes=i)).isoformat() + "Z"}
                    for i in (3, 4)], {}
        return [], {"cache": "unknown"}

    monkeypatch.setattr("openbq_kdb.aggregate.aggregate_ticks", aggregate)
    monkeypatch.setattr(gapfill, "recent_minutes", recent)
    monkeypatch.setattr(main_mod, "fetch_series", fake_series)
    return seen


def main_mod_resample(rows, interval):
    from app.series import resample

    return rows if interval == "1m" else resample(rows, interval)


def _build(symbol, interval, key="k"):
    return asyncio.run(main_mod.build_series(
        symbol, interval, "2026-10-16", "2026-10-16", _Recorder(), timedelta(days=1),
        gap_key=key))


def test_us_gap_is_filled_from_recent_minutes_and_ticks_win(wired):
    bars, meta = _build("AAPL", "1m")
    by_minute = {main_mod_dt(b["date"]): b["close"] for b in bars}
    assert by_minute[T0 + timedelta(minutes=2)] == 10  # tick bar kept over the fill
    assert [by_minute[T0 + timedelta(minutes=i)] for i in (3, 4, 5, 6)] == [20] * 4
    assert meta["rows_from_gapfill"] == 4
    assert wired["history"] == [("AAPL", "k")]


def test_a_wider_width_is_rebuilt_from_the_filled_minutes(wired):
    bars, _ = _build("AAPL", "5m")
    first = next(b for b in bars if main_mod_dt(b["date"]) == T0)
    assert first["volume"] == 3 + 3 * 2  # three tick minutes of 1, two fills of 3


def test_crypto_gap_is_filled_from_intraday_1m(wired):
    _, meta = _build("BTC-USD", "1m")
    # two intraday 1m calls: the chart's own history, then the fill over the tick span
    assert wired["crypto"] == [("2026-10-16", "2026-10-16")] * 2 and wired["history"] == []
    assert meta["rows_from_gapfill"] == 2


def test_no_fill_without_the_key_or_under_a_minute(wired):
    _, meta = _build("AAPL", "1m", key=None)
    assert meta.get("rows_from_gapfill", 0) == 0
    _, meta = _build("AAPL", "1s")
    assert meta.get("rows_from_gapfill", 0) == 0
    assert wired["history"] == []


def test_a_failed_fill_still_serves_the_ticks(wired, monkeypatch):
    async def broken(symbol, key):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(gapfill, "recent_minutes", broken)
    bars, meta = _build("AAPL", "1m")
    assert len(bars) == 6 and meta.get("rows_from_gapfill", 0) == 0


def main_mod_dt(value):
    from app.series import _row_dt

    return _row_dt(value)
