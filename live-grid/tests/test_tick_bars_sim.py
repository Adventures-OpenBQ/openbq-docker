# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""`GET /ticks?interval=` over the real KdbSession, KdbStore, TickRecorder and aggregate_ticks
(pandas Timestamps and all): q modelled by v10/kdb/source/q/tests/tickplant_sim.py as
test_lake_readback does, and a real session with nothing on its port. No q, no network."""
from __future__ import annotations

import importlib.util
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_SIM = (Path(__file__).resolve().parents[2] / "v10" / "kdb" / "source" / "q" / "tests"
        / "tickplant_sim.py")
_spec = importlib.util.spec_from_file_location("tickplant_sim", _SIM)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)


@pytest.fixture(autouse=True)
def no_history(monkeypatch):
    async def fetch_series(*args, **kwargs):
        raise AssertionError("fetch_series must never be called by /ticks")
    monkeypatch.setattr("app.main.fetch_series", fetch_series)


@pytest.fixture
def kdb_env(monkeypatch, tmp_path):
    for name in ("KDB_HOST", "QHOME", "KDB_LOCAL_QHOME", "LIVE_GRID_LAKE_READBACK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("KDB_EMBEDDED", "false")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "watchlist.json"))


def test_the_route_over_the_real_store_and_the_simulated_plant(monkeypatch, tmp_path, kdb_env):
    from openbq_kdb import session as session_mod
    from openbq_kdb.session import KdbSession

    today = datetime.now(timezone.utc).date()
    host = sim.Host(tmp_path / "kdb", today=lambda: today)
    plant = host.start()
    t0 = datetime.combine(today, datetime.min.time()) + timedelta(seconds=30)
    plant.upd("trades", pd.DataFrame(
        [(t0 + timedelta(seconds=15 * i), "AAPL", 100.0 + i, 1.0) for i in range(12)],
        columns=["time", "sym", "price", "size"]))
    monkeypatch.setattr(KdbSession, "_connect", lambda self, host_=None, **k: host.connect())
    monkeypatch.setattr(session_mod, "_RETRY_AFTER_S", 0.0)
    monkeypatch.setenv("KDB_BIND_HOST", "kdb")
    monkeypatch.setenv("KDB_PORT", "5000")

    body = TestClient(create_app(api_key="test-key")).get(
        f"/ticks?symbol=AAPL&interval=1m&start={today}").json()
    # ticks 00:00:30-00:03:15: 00:00 is only partly covered, so the bars are 00:01-00:03
    assert [b["date"][11:] for b in body["bars"]] == ["00:01:00Z", "00:02:00Z", "00:03:00Z"]
    assert body["bars"][0]["open"] == 102.0 and body["bars"][-1]["close"] == 111.0
    assert body["span"] == {"first": f"{today}T00:00:30Z", "last": f"{today}T00:03:15Z"}


def test_an_unreachable_kdb_is_a_503_for_the_interval_form(monkeypatch, kdb_env):
    """The real KdbSession with nothing on its port: the IPC failure itself, not a fake."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("KDB_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("KDB_PORT", str(port))
    res = TestClient(create_app(api_key="test-key")).get("/ticks?symbol=AAPL&interval=1m")
    assert res.status_code == 503 and res.json() == {"detail": "tick store unavailable"}
