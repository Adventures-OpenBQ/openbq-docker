# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""openbq-docker v10: what this line adds on top of the ported live-grid suite.

1. History through openbq-api's EODHD namespace (OPENBB_HISTORY_NAMESPACE=eodhd), since
   openbq-api installs no standard routers and no openbb-kdb provider.
2. live-grid without kdb: the REAL openbq_kdb session pointed at a port nothing listens on
   (no monkeypatched store, no licence, no q), as the `live` profile runs when the kdb
   service is absent or has exited. Every surface must still answer.

Nothing here calls EODHD or the network: the API is an httpx MockTransport serving the
recorded-shape fixture in tests/fixtures/openbq_eodhd_history.json (fictional values).
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import openbb_client
from app.main import create_app
from tests.test_main import FakeRest, _NullWs

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "openbq_eodhd_history.json").read_text()
)


@pytest.fixture
def api(monkeypatch):
    """Route every httpx.AsyncClient openbb_client builds to a recorded openbq-api."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FIXTURE)

    real = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    return seen


# -- 1. the history namespace -------------------------------------------------

def test_without_a_namespace_the_donor_route_and_provider_are_kept(monkeypatch):
    monkeypatch.delenv("OPENBB_HISTORY_NAMESPACE", raising=False)
    assert openbb_client.history_route("AAPL", "kdb") == ("equity/price/historical", "kdb")
    assert openbb_client.history_route("BTC-USD", "eodhd") == ("crypto/price/historical", "eodhd")


@pytest.mark.parametrize("symbol,route", [
    ("AAPL", "eodhd/equity/price/historical"),
    ("BTC-USD", "eodhd/crypto/price/historical"),
    ("EURUSD", "eodhd/currency/price/historical"),
])
def test_the_eodhd_namespace_routes_every_asset_class_and_pins_its_provider(monkeypatch, symbol, route):
    monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", "eodhd")
    # `kdb` is what every live-grid route defaults to; the namespace offers eodhd only.
    assert openbb_client.history_route(symbol, "kdb") == (route, "eodhd")
    assert openbb_client.history_route(symbol, "eodhd") == (route, "eodhd")


@pytest.mark.parametrize("namespace", [None, "eodhd"])
def test_futures_history_goes_to_yfinance_whatever_the_namespace(monkeypatch, namespace):
    if namespace:
        monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", namespace)
    else:
        monkeypatch.delenv("OPENBB_HISTORY_NAMESPACE", raising=False)
    for provider in ("kdb", "eodhd"):
        assert openbb_client.history_route("CL=F", provider) == (
            "yfinance/futures/historical", "yfinance")


async def test_fetch_series_calls_the_namespace_with_the_pair(monkeypatch, api):
    monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", "/eodhd/")
    monkeypatch.setattr(openbb_client, "OPENBB_URL", "http://openbq-api:6900")
    monkeypatch.setattr(openbb_client, "USERNAME", "stack")
    monkeypatch.setattr(openbb_client, "PASSWORD", "synthetic")
    bars, meta = await openbb_client.fetch_series("AAPL", "1d", "2026-09-01", "2026-09-03", "kdb")
    assert [b["close"] for b in bars] == [101.0, 102.5, 103.0]
    # No kdb cache in front of openbq-api, so no results_metadata: the donor's "unknown".
    assert meta["cache"] == "unknown"
    (request,) = api
    assert request.url.path == "/api/v1/eodhd/equity/price/historical"
    assert dict(request.url.params) == {
        "symbol": "AAPL", "provider": "eodhd", "interval": "1d",
        "start_date": "2026-09-01", "end_date": "2026-09-03",
    }
    assert request.headers["authorization"].startswith("Basic ")


# -- 2. no kdb ----------------------------------------------------------------

def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def no_kdb(monkeypatch, api):
    """The `live` profile with no reachable q: the real KdbSession, nothing on its port."""
    for name in ("KDB_HOST", "QHOME", "KDB_LOCAL_QHOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("KDB_EMBEDDED", "false")
    monkeypatch.setenv("KDB_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("KDB_PORT", str(_closed_port()))
    monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", "eodhd")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", "/nonexistent/watchlist.json")
    app = create_app(api_key="test-key", seed_client=FakeRest(),
                     client_factory=lambda *a, **k: _NullWs())
    with TestClient(app) as client:
        yield client


def test_without_kdb_health_answers_and_says_the_store_is_not_connected(no_kdb):
    body = no_kdb.get("/health").json()
    assert body["status"] == "ok"
    assert body["ticks"]["endpoint"] is None
    assert body["ticks"]["written"] == 0


def test_without_kdb_the_tick_reader_is_an_empty_200(no_kdb):
    res = no_kdb.get("/ticks?symbol=AAPL")
    assert res.status_code == 200
    assert res.json() == {"symbol": "AAPL", "ticks": []}


def test_without_kdb_the_grid_still_seeds_from_the_vendor(no_kdb):
    rows = no_kdb.get("/live_grid?symbol=AAPL,MSFT").json()
    assert [r["symbol"] for r in rows] == ["AAPL", "MSFT"]
    assert all(r["price"] == 100.0 for r in rows)


def test_without_kdb_series_and_charts_are_history_only(no_kdb):
    for interval in ("1d", "1m"):  # 1m is tick-capable: the seam is tried and skipped
        body = no_kdb.get(f"/series?symbol=AAPL&interval={interval}"
                          "&start=2026-09-01&end=2026-09-03").json()
        assert [b["close"] for b in body["bars"]] == [101.0, 102.5, 103.0]
        assert body["cache"]["rows_from_ticks"] == 0
        assert body["cache"]["seam"] is None
    chart = no_kdb.get("/chart?symbol=AAPL&start=2026-09-01&end=2026-09-03")
    assert chart.status_code == 200 and chart.json()["data"]
    ta = no_kdb.get("/ta_chart?symbol=AAPL&start=2026-09-01&end=2026-09-03&indicators=sma:period=2")
    assert ta.status_code == 200
    assert "bars unavailable" not in ta.json()["layout"]["title"]["text"]


def test_without_kdb_the_grid_socket_still_streams(no_kdb):
    with no_kdb.websocket_connect("/live_grid_ws") as ws:
        ws.send_json({"params": {"symbol": "AAPL"}})
        # The manager registered the symbol; nothing about kdb closed the socket.
        ws.send_json({"params": {"symbol": "AAPL,MSFT"}})
    assert no_kdb.get("/health").status_code == 200


def test_without_kdb_widgets_and_apps_are_served(no_kdb):
    widgets = no_kdb.get("/widgets.json").json()
    assert {"live_grid", "kdb_ticks", "kdb_cache_chart", "live_chart", "ta_chart"} <= set(widgets)
    apps = no_kdb.get("/apps.json").json()
    assert [a["name"] for a in apps] == ["Example Dashboard - Version 10.0.0 - Live Grid"]
