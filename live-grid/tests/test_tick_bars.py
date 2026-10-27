# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""app.tick_bars: bars from kdb and the lake only (live-composed-bars spec §4).

kdb is a fake store, the lake a local Delta directory written as eod-dump writes it.
No q, no network, no EODHD, no openbq-api: `no_history` fails any test that reaches them.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import tick_bars as tick_bars_mod
from app.lake import LakeTicks
from app.tick_bars import TicksRequestError, parse_start, tick_bars
from tests.tick_fakes import D, FakeRecorder, FakeStore, flush, minute_bars
from tests.tick_fakes import fake_aggregate, no_history  # noqa: F401 - used by pytestmark

pytestmark = pytest.mark.usefixtures("fake_aggregate", "no_history")

TODAY = date(2026, 10, 12)
D3 = date(2026, 10, 11)


# -- parse_start ---------------------------------------------------------------------

@pytest.mark.parametrize(("raw", "want"), [
    ("2026-10-14", D("2026-10-14T00:00:00")),
    ("2026-10-14T08:00:00", D("2026-10-14T08:00:00")),
    ("2026-10-14T08:00:00Z", D("2026-10-14T08:00:00")),
    ("2026-10-14T04:00:00-04:00", D("2026-10-14T08:00:00")),
    ("2026-10-14T08:00:00+00:00", D("2026-10-14T08:00:00")),
])
def test_start_is_naive_utc(raw, want):
    assert parse_start(raw) == want


@pytest.mark.parametrize("raw", ["yesterday", "2026-13-01", "2026-10-14T08:00:00 00:00",
                                 "14/10/2026"])
def test_a_bad_start_is_a_request_error(raw):
    """The third is `+00:00` sent unencoded: a query string reads its '+' as a space."""
    with pytest.raises(TicksRequestError):
        parse_start(raw)


# -- over a fake store -----------------------------------------------------------------

async def test_the_answer_is_symbol_interval_bars_and_span_in_iso_utc():
    store = FakeStore((D("2026-10-12T13:59:30"), D("2026-10-12T14:02:10")),
                      minute_bars("2026-10-12T14:00:00", "2026-10-12T14:02:00"))
    got = await tick_bars("AAPL", "1m", None, FakeRecorder(store), None, today=TODAY)
    assert set(got) == {"symbol", "interval", "bars", "span"}
    assert got["symbol"] == "AAPL" and got["interval"] == "1m"
    assert got["span"] == {"first": "2026-10-12T13:59:30Z", "last": "2026-10-12T14:02:10Z"}
    assert [b["date"] for b in got["bars"]] == ["2026-10-12T14:00:00Z", "2026-10-12T14:01:00Z",
                                                "2026-10-12T14:02:00Z"]
    assert got["bars"][0] == {"date": "2026-10-12T14:00:00Z", "open": 1.0, "high": 2.0,
                              "low": 0.5, "close": 1.5, "volume": 10.0, "vwap": 1.2}
    # the seam rule: 13:59 is only partly covered, so kdb owns from 14:00
    assert store.aggregate_calls == [("1m", D("2026-10-12T14:00:00"), D("2026-10-12T14:02:10"))]


async def test_a_start_inside_the_span_starts_the_bars_there():
    store = FakeStore((D("2026-10-12T07:00:00"), D("2026-10-12T09:00:00")),
                      minute_bars("2026-10-12T07:00:00", "2026-10-12T09:00:00"))
    got = await tick_bars("AAPL", "1m", "2026-10-12T08:00:00+00:00", FakeRecorder(store), None,
                          today=TODAY)
    assert got["bars"][0]["date"] == "2026-10-12T08:00:00Z"
    assert got["span"]["first"] == "2026-10-12T07:00:00Z"  # the span is what kdb holds


async def test_a_start_off_the_bucket_grid_starts_at_the_next_bucket():
    store = FakeStore((D("2026-10-12T07:00:00"), D("2026-10-12T09:00:00")))
    await tick_bars("AAPL", "5m", "2026-10-12T08:01:30Z", FakeRecorder(store), None, today=TODAY)
    assert store.aggregate_calls[0][1] == D("2026-10-12T08:05:00")


async def test_a_date_start_is_that_utc_midnight():
    store = FakeStore((D("2026-10-11T22:00:00"), D("2026-10-12T09:00:00")))
    await tick_bars("AAPL", "1m", "2026-10-12", FakeRecorder(store), None, today=TODAY)
    assert store.aggregate_calls[0][1] == D("2026-10-12T00:00:00")


async def test_a_start_after_the_last_tick_is_no_bars_but_still_the_span():
    store = FakeStore((D("2026-10-12T07:00:00"), D("2026-10-12T09:00:00")))
    got = await tick_bars("AAPL", "1m", "2026-10-12T10:00:00Z", FakeRecorder(store), None,
                          today=TODAY)
    assert got["bars"] == [] and got["span"]["last"] == "2026-10-12T09:00:00Z"
    assert store.aggregate_calls == []


async def test_an_empty_store_is_no_bars_and_no_span():
    store = FakeStore(None)
    got = await tick_bars("AAPL", "1m", "2026-10-12", FakeRecorder(store), None, today=TODAY)
    assert got == {"symbol": "AAPL", "interval": "1m", "bars": [], "span": None}
    assert store.aggregate_calls == []


async def test_no_recorder_is_no_bars_and_no_span():
    got = await tick_bars("AAPL", "1m", None, None, None, today=TODAY)
    assert got == {"symbol": "AAPL", "interval": "1m", "bars": [], "span": None}


@pytest.mark.parametrize("interval", ["1w", "1mo", "1M", "", "0m", "2d"])
async def test_an_interval_the_ticks_cannot_build_is_a_request_error(interval):
    """`2d` parses but is wider than the one-day window: tick_capable says no."""
    with pytest.raises(TicksRequestError):
        await tick_bars("AAPL", interval, None, FakeRecorder(FakeStore()), None, today=TODAY)


async def test_more_than_max_bars_is_refused_not_cut(monkeypatch):
    monkeypatch.setattr(tick_bars_mod, "MAX_BARS", 2)
    store = FakeStore((D("2026-10-12T14:00:00"), D("2026-10-12T14:02:00")),
                      minute_bars("2026-10-12T14:00:00", "2026-10-12T14:02:00"))
    with pytest.raises(TicksRequestError, match="more than 2"):
        await tick_bars("AAPL", "1m", None, FakeRecorder(store), None, today=TODAY)


def test_the_cap_fits_one_minute_bars_over_every_day_the_lake_reads_by_default():
    assert tick_bars_mod.MAX_BARS == 20_000
    assert timedelta(minutes=tick_bars_mod.MAX_BARS) > timedelta(days=11)


async def test_a_kdb_failure_propagates():
    store = FakeStore(ConnectionError("kdb unreachable"))
    with pytest.raises(ConnectionError):
        await tick_bars("AAPL", "1m", None, FakeRecorder(store), None, today=TODAY)


# -- the lake read-back -----------------------------------------------------------------

async def test_flushed_days_come_before_kdb_which_owns_only_what_follows(tmp_path):
    flush(tmp_path, D3, start_hm=(14, 30))           # 14:30-14:32 on D3
    store = FakeStore((D("2026-10-11T23:58:10"), D("2026-10-12T14:02:00")),
                      minute_bars("2026-10-11T23:59:00", "2026-10-12T14:02:00"))
    got = await tick_bars("AAPL", "1m", D3.isoformat(), FakeRecorder(store),
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    dates = [b["date"] for b in got["bars"]]
    assert dates[:3] == ["2026-10-11T14:30:00Z", "2026-10-11T14:31:00Z", "2026-10-11T14:32:00Z"]
    assert got["bars"][0]["open"] == 100.0          # the flushed ticks, not a fake row
    # kdb from its own seam (23:59), after the lake's last bucket (14:33)
    assert store.aggregate_calls[0][1] == D("2026-10-11T23:59:00")
    assert dates[3] == "2026-10-11T23:59:00Z" and dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert got["span"]["first"] == "2026-10-11T23:58:10Z"   # kdb's, not the lake's


async def test_kdb_never_starts_inside_a_flushed_days_span(tmp_path):
    flush(tmp_path, D3, start_hm=(23, 50), minutes=5)  # 23:50-23:54 on D3
    store = FakeStore((D("2026-10-11T23:52:00"), D("2026-10-12T00:05:00")),
                      minute_bars("2026-10-11T23:52:00", "2026-10-12T00:05:00"))
    got = await tick_bars("AAPL", "1m", D3.isoformat(), FakeRecorder(store),
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    assert store.aggregate_calls[0][1] == D("2026-10-11T23:55:00")
    dates = [b["date"] for b in got["bars"]]
    assert len(dates) == len(set(dates)) and dates == sorted(dates)


async def test_a_start_before_the_lakes_reach_reads_only_max_days(tmp_path):
    for day in (date(2026, 10, 1), date(2026, 10, 10), D3):
        flush(tmp_path, day)
    got = await tick_bars("AAPL", "1m", "2026-09-01", FakeRecorder(FakeStore(None)),
                          LakeTicks(str(tmp_path), {}, max_days=2), today=TODAY)
    assert sorted({b["date"][:10] for b in got["bars"]}) == ["2026-10-10", "2026-10-11"]
    assert got["span"] is None


async def test_a_datetime_start_drops_that_days_earlier_lake_bars(tmp_path):
    flush(tmp_path, D3, start_hm=(14, 30))
    got = await tick_bars("AAPL", "1m", "2026-10-11T14:31:00Z", None,
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    assert [b["date"] for b in got["bars"]] == ["2026-10-11T14:31:00Z", "2026-10-11T14:32:00Z"]


async def test_without_start_the_lake_is_not_read(tmp_path):
    flush(tmp_path, D3)
    got = await tick_bars("AAPL", "1m", None, FakeRecorder(FakeStore(None)),
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    assert got["bars"] == []


async def test_a_daily_interval_never_reads_the_lake(tmp_path):
    flush(tmp_path, D3)
    got = await tick_bars("AAPL", "1d", D3.isoformat(), FakeRecorder(FakeStore(None)),
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    assert got["bars"] == []


async def test_today_is_never_read_from_the_lake(tmp_path):
    flush(tmp_path, TODAY)  # a stray table for a day eod-dump has not finished
    got = await tick_bars("AAPL", "1m", TODAY.isoformat(), FakeRecorder(FakeStore(None)),
                          LakeTicks(str(tmp_path), {}), today=TODAY)
    assert got["bars"] == []


async def test_a_lake_failure_propagates(tmp_path):
    class Broken(LakeTicks):
        def read_day(self, symbol, day):
            raise OSError("connection refused")

    with pytest.raises(OSError):
        await tick_bars("AAPL", "1m", D3.isoformat(), FakeRecorder(FakeStore(None)),
                        Broken(str(tmp_path), {}), today=TODAY)


async def test_a_punctuated_symbols_flushed_day_is_found_under_eod_dumps_key(tmp_path):
    flush(tmp_path, D3, sym="BTC-USD")  # BTC_USD_2026_10_11
    got = await tick_bars("BTC-USD", "1m", D3.isoformat(), None, LakeTicks(str(tmp_path), {}),
                          today=TODAY)
    assert len(got["bars"]) == 3 and got["symbol"] == "BTC-USD"
