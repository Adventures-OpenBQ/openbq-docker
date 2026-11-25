# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Which EODHD interval history is fetched at, and how a chart width is built from it.

EODHD intraday serves 1m and 5m (one 1m request spans at most 120 days); 1h is
stamped on the half hour, so it never meets the tick buckets. A width is built
only from a source that divides it evenly; a width below a minute has no
history source at all, only ticks.
"""

import asyncio
from datetime import date, datetime, timedelta

import pytest

from app import main as main_mod
from app.series import history_source, one_minute_window, resample


@pytest.mark.parametrize("interval, source", [
    ("1s", None), ("30s", None),
    ("1m", "1m"), ("2m", "1m"), ("7m", "1m"),
    ("5m", "5m"), ("15m", "5m"), ("30m", "5m"), ("1h", "5m"), ("4h", "5m"),
    ("1d", "1d"),
    ("1w", "1w"),  # not a fixed width: the provider's own, as before
])
def test_history_source_divides_evenly(interval, source):
    assert history_source(interval) == source


def test_one_minute_window_is_one_request_ending_at_end():
    """Review finding 1: a 1m window is clamped to the one request EODHD accepts
    (120 days), ending at `end`, so no `start` can fan one request out."""
    lo, hi = one_minute_window("1900-01-01", "2026-10-17")
    assert hi == "2026-10-17"
    assert (date.fromisoformat(hi) - date.fromisoformat(lo)).days == 119


def test_one_minute_window_leaves_a_short_window_alone():
    assert one_minute_window("2026-10-12", "2026-10-17") == ("2026-10-12", "2026-10-17")


def test_one_minute_window_passes_a_reversed_or_unparseable_window_through():
    """Review finding 2: a reversed window used to raise IndexError."""
    assert one_minute_window("2026-10-17", "2026-10-01") == ("2026-10-17", "2026-10-01")
    assert one_minute_window("soon", "2026-10-01") == ("soon", "2026-10-01")


def test_resample_builds_15m_from_5m_on_the_clock_grid():
    rows = [
        {"date": "2026-10-16T13:30:00Z", "open": 1, "high": 3, "low": 1, "close": 2, "volume": 10},
        {"date": "2026-10-16T13:35:00Z", "open": 2, "high": 5, "low": 2, "close": 4, "volume": 20},
        {"date": "2026-10-16T13:40:00Z", "open": 4, "high": 4, "low": 0.5, "close": 3, "volume": None},
        {"date": "2026-10-16T13:45:00Z", "open": 3, "high": 3, "low": 3, "close": 3, "volume": 5},
    ]
    out = resample(rows, "15m")
    assert [r["date"] for r in out] == ["2026-10-16T13:30:00Z", "2026-10-16T13:45:00Z"]
    assert out[0] == {"date": "2026-10-16T13:30:00Z", "open": 1, "high": 5, "low": 0.5,
                      "close": 3, "volume": 30}
    assert out[1]["volume"] == 5


def test_resample_carries_a_volume_weighted_vwap():
    """Review finding 4: a filled series kept vwap on none of its bars."""
    rows = [
        {"date": "2026-10-16T13:30:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 10, "vwap": 1.0},
        {"date": "2026-10-16T13:31:00Z", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 30, "vwap": 2.0},
        {"date": "2026-10-16T13:32:00Z", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 5},
    ]
    assert resample(rows[:2], "5m")[0]["vwap"] == pytest.approx((10 * 1 + 30 * 2) / 40)
    # A traded minute with no vwap (a filled one) makes the bucket's vwap unknown, not a
    # vwap of the other minutes' volume alone (re-review, 2026-10-18).
    assert "vwap" not in resample(rows, "5m")[0]
    assert "vwap" not in resample([{**rows[2], "date": "2026-10-16T13:40:00Z"}], "5m")[0]


def test_resample_keeps_a_bucket_with_no_volume_as_none():
    rows = [{"date": "2026-10-16T20:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1,
             "volume": None}]
    assert resample(rows, "15m")[0]["volume"] is None


class _Store:
    def tick_span(self, symbol):
        return (datetime(2026, 10, 17, 14, 0, 3), datetime(2026, 10, 17, 14, 9, 59))


class _Recorder:
    store = _Store()


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def fake_history(symbol, interval, start, end, provider="kdb"):
        seen.append((interval, start, end))
        return ([{"date": f"{start}T13:30:00Z", "open": 1, "high": 1, "low": 1,
                  "close": 1, "volume": 1}], {"cache": "unknown"})

    monkeypatch.setattr(main_mod, "fetch_series", fake_history)
    monkeypatch.setattr("openbq_kdb.aggregate.aggregate_ticks",
                        lambda store, sym, interval, lo, hi: [
                            {"date": lo, "open": 2, "high": 2, "low": 2, "close": 2,
                             "volume": 1}])
    return seen


def _build(interval, start="2026-10-12", end="2026-10-17"):
    return asyncio.run(main_mod.build_series("AAPL", interval, start, end, _Recorder(),
                                             timedelta(days=1)))


def test_tick_only_width_skips_history(calls):
    bars, meta = _build("1s")
    assert calls == []
    assert meta["rows_from_ticks"] == 1 and len(bars) == 1


def test_15m_is_fetched_at_5m(calls):
    bars, _ = _build("15m")
    assert [c[0] for c in calls] == ["5m"]
    assert bars[0]["date"] == "2026-10-12T13:30:00Z"


def test_1m_from_long_ago_is_one_fetch(calls):
    """Review finding 1: start=1900-01-01 made 386 sequential fetches."""
    _build("1m", "1900-01-01", "2026-10-17")
    assert len(calls) == 1 and calls[0][0] == "1m" and calls[0][2] == "2026-10-17"


def test_series_defaults_intraday_to_five_days(monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_history(symbol, interval, start, end, provider="kdb"):
        return [], {"cache": "unknown"}

    monkeypatch.setattr(main_mod, "fetch_series", fake_history)
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    client = TestClient(main_mod.create_app(api_key="test-key"))
    today = date.today()
    minute = client.get("/series", params={"symbol": "AAPL", "interval": "1m"}).json()
    daily = client.get("/series", params={"symbol": "AAPL", "interval": "1d"}).json()
    assert minute["start"] == str(today - timedelta(days=5))
    assert daily["start"] == str(today - timedelta(days=365))
