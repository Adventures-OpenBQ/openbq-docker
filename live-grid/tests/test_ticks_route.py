# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""`GET /ticks`: the raw form unchanged, the interval form over a fake kdb store and a local
lake, and Basic auth over it. No q, no network, no EODHD, no openbq-api."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.lake import LakeTicks
from app.main import create_app
from tests.tick_fakes import D, FakeStore, flush, minute_bars
from tests.tick_fakes import fake_aggregate, no_history  # noqa: F401 - used by pytestmark

pytestmark = pytest.mark.usefixtures("fake_aggregate", "no_history")


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def wire(monkeypatch, store):
    """create_app builds its TickRecorder around `store` instead of a real KdbStore."""
    monkeypatch.setattr("openbq_kdb.config.resolve_config", lambda: object())
    monkeypatch.setattr("openbq_kdb.session.KdbSession", lambda config: object())
    monkeypatch.setattr("openbq_kdb.store.KdbStore", lambda session: store)


@pytest.fixture
def client(wire):
    return TestClient(create_app(api_key="test-key"))


@pytest.fixture
def lake_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_GRID_LAKE_READBACK", "true")
    monkeypatch.setenv("DELTA_URI", str(tmp_path))
    return tmp_path


def test_the_route_answers_what_arts_charts_sends_and_validates(client, store):
    """LiveGridBars asks `interval=1m` from an aware `start` (`+00:00`, sent as %2B00:00),
    then checks every bar's date parses and OHLC are numbers, and reads span.first."""
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    store.span = (now - timedelta(minutes=3), now)
    store.rows = minute_bars((now - timedelta(minutes=2)).isoformat(), now.isoformat())
    start = (now - timedelta(minutes=10)).replace(tzinfo=timezone.utc).isoformat()
    res = client.get("/ticks", params={"symbol": "aapl", "interval": "1m", "start": start})
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "AAPL" and body["interval"] == "1m" and len(body["bars"]) == 3
    for bar in body["bars"]:
        datetime.fromisoformat(bar["date"].replace("Z", "+00:00"))
        assert all(isinstance(bar[k], float) for k in ("open", "high", "low", "close"))
    datetime.fromisoformat(body["span"]["first"].replace("Z", "+00:00"))


def test_the_raw_form_is_unchanged(client, store):
    """Without `interval`: the newest ticks, `limit` capped at 1000; `start` alone changes
    nothing."""
    store.ticks = [{"time": D("2026-09-03T15:00:02"), "price": 191.5, "size": 100.0}]
    res = client.get("/ticks?symbol=aapl&limit=99999&start=2026-01-01")
    assert res.status_code == 200
    assert res.json() == {"symbol": "AAPL", "ticks": [
        {"time": "2026-09-03T15:00:02", "price": 191.5, "size": 100.0}]}


@pytest.mark.parametrize("query", ["interval=1w", "interval=1m&start=yesterday",
                                   "interval=1m&start=2026-10-14T08:00:00+00:00"])
def test_a_bad_interval_or_start_is_422(client, query):
    """The last is an unencoded '+', which a query string reads as a space."""
    res = client.get(f"/ticks?symbol=AAPL&{query}")
    assert res.status_code == 422 and res.json()["detail"]


def test_an_empty_symbol_is_422(client):
    assert client.get("/ticks?symbol=%20&interval=1m").status_code == 422


def test_an_empty_store_is_an_empty_200(client, store):
    store.span = None
    res = client.get("/ticks?symbol=AAPL&interval=1m")
    assert res.status_code == 200
    assert res.json() == {"symbol": "AAPL", "interval": "1m", "bars": [], "span": None}


def test_no_recorder_is_an_empty_200(monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    res = TestClient(create_app(api_key="test-key")).get("/ticks?symbol=AAPL&interval=1m")
    assert res.status_code == 200
    assert res.json() == {"symbol": "AAPL", "interval": "1m", "bars": [], "span": None}


def test_a_kdb_failure_is_503_and_the_raw_form_still_degrades_to_200(client, store):
    """An empty 200 would read as 'no ticks held' and the caller would draw a gap; 503 sends
    it back to its own history. The raw form keeps its documented empty 200."""
    store.span = ConnectionError("kdb unreachable")
    res = client.get("/ticks?symbol=AAPL&interval=1m")
    assert res.status_code == 503 and res.json() == {"detail": "tick store unavailable"}

    def boom(symbol, limit):
        raise ConnectionError("kdb unreachable")
    store.read_ticks = boom
    assert client.get("/ticks?symbol=AAPL").json() == {"symbol": "AAPL", "ticks": []}


def test_the_route_reads_the_lake_the_app_was_given(wire, lake_dir):
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    flush(lake_dir, yesterday)
    body = TestClient(create_app(api_key="test-key")).get(
        f"/ticks?symbol=AAPL&interval=1m&start={yesterday}").json()
    assert [b["date"][11:16] for b in body["bars"]] == ["14:30", "14:31", "14:32"]


def test_a_lake_failure_is_503(monkeypatch, wire, lake_dir):
    def broken(self, symbol, day):
        raise OSError("connection refused")
    monkeypatch.setattr(LakeTicks, "read_day", broken)
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    res = TestClient(create_app(api_key="test-key")).get(
        f"/ticks?symbol=AAPL&interval=1m&start={yesterday}")
    assert res.status_code == 503


def _basic(user="alice", pw="s3cret"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_the_interval_form_is_behind_basic_auth(monkeypatch):
    monkeypatch.setenv("OPENBB_API_AUTH", "true")
    monkeypatch.setenv("OPENBB_API_USERNAME", "alice")
    monkeypatch.setenv("OPENBB_API_PASSWORD", "s3cret")
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    guarded = TestClient(create_app(api_key="test-key"))
    url = "/ticks?symbol=AAPL&interval=1m"
    assert guarded.get(url).status_code == 401
    assert guarded.get(url, headers=_basic(pw="no")).status_code == 401
    assert guarded.get(url, headers=_basic()).status_code == 200
