# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Fakes for the `GET /ticks?interval=` tests: a kdb store, a recorder, flushed lake days,
and two fixtures a test module opts into with
`pytestmark = pytest.mark.usefixtures("fake_aggregate", "no_history")`."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from deltalake import write_deltalake

from app.lake import table_key

D = datetime.fromisoformat


def minute_bars(first: str, last: str) -> list[dict]:
    """What aggregate_ticks returns: naive-UTC datetimes, one bar a minute."""
    at, end, rows = D(first), D(last), []
    while at <= end:
        rows.append({"date": at, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
                     "volume": 10.0, "vwap": 1.2})
        at += timedelta(minutes=1)
    return rows


class FakeStore:
    """KdbStore's tick_span and read_ticks; `fake_aggregate` serves `rows` in its range.
    A `span` that is an exception is raised, as KdbStore._call raises on a dead kdb."""

    def __init__(self, span=None, rows=()):
        self.span, self.rows = span, list(rows)
        self.aggregate_calls: list[tuple] = []
        self.ticks: list[dict] = []

    def tick_span(self, symbol):
        if isinstance(self.span, Exception):
            raise self.span
        return self.span

    def read_ticks(self, symbol, limit):
        return self.ticks

    def prune_ticks(self, cutoff):
        return 0

    def write_ticks(self, frame):
        return 0


class FakeRecorder:
    def __init__(self, store, window=timedelta(days=1)):
        self.store, self.window = store, window


def flush(base, day: date, start_hm=(14, 30), minutes=3, sym="AAPL"):
    """eod_dump's Delta table for one (symbol, day): four ticks a minute, prices from 100."""
    t0 = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_hm[0],
                                                               minutes=start_hm[1])
    frame = pd.DataFrame([(t0 + timedelta(seconds=15 * i), 100.0 + i, 1.0)
                          for i in range(minutes * 4)], columns=["date", "price", "size"])
    write_deltalake(f"{base}/ticks_live/{table_key(sym, day)}", frame, mode="overwrite",
                    schema_mode="overwrite")


@pytest.fixture
def fake_aggregate(monkeypatch):
    """aggregate_ticks over a FakeStore: its rows in [start, end], each call recorded."""
    def aggregate(store, symbol, interval, start, end):
        store.aggregate_calls.append((interval, start, end))
        return [r for r in store.rows if start <= r["date"] <= end]
    monkeypatch.setattr("openbq_kdb.aggregate.aggregate_ticks", aggregate)


@pytest.fixture
def no_history(monkeypatch):
    """fetch_series and every outbound async HTTP request fail the test if reached."""
    async def fetch_series(*args, **kwargs):
        raise AssertionError("fetch_series must never be called by /ticks")

    async def send(self, request, *args, **kwargs):
        raise AssertionError(f"/ticks made an outbound request to {request.url}")

    monkeypatch.setattr("app.main.fetch_series", fetch_series)
    monkeypatch.setattr("app.openbb_client.fetch_series", fetch_series)
    monkeypatch.setattr("httpx.AsyncClient.send", send)
