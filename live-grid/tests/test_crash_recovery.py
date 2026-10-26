# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbq-docker v10: live-grid across a kdb restart, and a restarted live-grid.

The kdb service is v10/kdb/source/q/tests/tickplant_sim.py, a model of startup.q +
persist.q: its tick log on a /data directory that outlives the process, and the
-11! replay on boot. live-grid's own code runs unmodified; only
`KdbSession._connect` dials the simulated host instead of PyKX. A real q run of
the same procedure is Mac-pending (docs/v10/live-grid-kdb-port.md).
"""
from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import build_series, create_app
from app.recorder import TickRecorder
from openbq_kdb import session as session_mod
from openbq_kdb.config import resolve_config
from openbq_kdb.session import KdbSession
from openbq_kdb.store import KdbStore
from tests.test_main import FakeRest, _NullWs
from tests.test_openbq_v10 import api  # noqa: F401 - the recorded openbq-api fixture

_SIM = Path(__file__).resolve().parents[2] / "v10" / "kdb" / "source" / "q" / "tests" / "tickplant_sim.py"
_spec = importlib.util.spec_from_file_location("tickplant_sim", _SIM)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)

T0 = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=2)


@pytest.fixture
def host(tmp_path, monkeypatch):
    h = sim.Host(tmp_path, today=date.today)
    monkeypatch.setattr(KdbSession, "_connect", lambda self, host=None: h.connect())
    monkeypatch.setattr(session_mod, "_RETRY_AFTER_S", 0.0)
    for name in ("KDB_HOST", "QHOME", "KDB_LOCAL_QHOME"):
        monkeypatch.delenv(name, raising=False)
    # live-grid's environment in docker-compose.yml
    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("KDB_EMBEDDED", "false")
    monkeypatch.setenv("KDB_BIND_HOST", "kdb")
    monkeypatch.setenv("KDB_PORT", "5000")
    monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", "eodhd")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", "/nonexistent/watchlist.json")
    return h


def _recorder():
    return TickRecorder(KdbStore(KdbSession(resolve_config())), window=timedelta(days=1))


def _record(recorder, n, start, sym="AAPL"):
    for i in range(n):
        recorder.record(sym, 100.0 + i % 7, 10, start + timedelta(seconds=i))
    return recorder.flush()


def _window():
    return (T0 - timedelta(days=1)).date().isoformat(), (T0 + timedelta(days=1)).date().isoformat()


async def test_a_kdb_killed_mid_session_comes_back_with_the_day_and_recording_resumes(host, api):
    host.start()
    recorder = _recorder()
    assert _record(recorder, 600, T0) == 600

    host.kill()
    # During the outage a flush fails and is counted as dropped -- the feed is not killed.
    assert _record(recorder, 5, T0 + timedelta(minutes=20)) == 0
    assert recorder.dropped == 5
    start, end = _window()
    bars, meta = await build_series("AAPL", "1m", start, end, recorder, recorder.window)
    assert meta["rows_from_ticks"] == 0  # no q: history only, no error

    host.start()  # q boots, persist.q replays tlog_<today>
    assert len(host.plant.trades) == 600
    assert recorder.store.tick_span("AAPL")[0] == T0
    bars, meta = await build_series("AAPL", "1m", start, end, recorder, recorder.window)
    assert meta["rows_from_ticks"] == 10  # 600 s of ticks = ten whole minutes
    assert meta["seam"] == T0.isoformat()
    # and recording resumes into the new log
    assert _record(recorder, 60, T0 + timedelta(minutes=30)) == 60
    host.kill()
    host.start()
    assert len(host.plant.trades) == 660
    recorder.store.session.close()


def test_a_restarted_live_grid_reads_the_day_back_from_kdb(host, api):
    host.start()
    first = _recorder()
    _record(first, 300, T0)
    first.store.session.close()  # live-grid's container is recreated; kdb keeps running

    app = create_app(api_key="test-key", seed_client=FakeRest(),
                     client_factory=lambda *a, **k: _NullWs())
    with TestClient(app) as client:
        ticks = client.get("/ticks?symbol=AAPL&limit=1000").json()["ticks"]
        assert len(ticks) == 300
        start, end = _window()
        body = client.get(f"/series?symbol=AAPL&interval=1m&start={start}&end={end}").json()
        assert body["cache"]["rows_from_ticks"] == 5
        assert body["cache"]["seam"] == T0.isoformat()
        # The configured endpoint is the Compose host, not loopback.
        assert client.get("/health").json()["ticks"]["endpoint"] == "kdb:5000"


def test_both_restart_kdb_first_then_live_grid(host, api):
    host.start()
    first = _recorder()
    _record(first, 120, T0)
    first.store.session.close()
    host.kill()  # the whole `live` profile goes down: docker compose --profile live restart
    host.start()
    app = create_app(api_key="test-key", seed_client=FakeRest(),
                     client_factory=lambda *a, **k: _NullWs())
    with TestClient(app) as client:
        assert len(client.get("/ticks?symbol=AAPL&limit=1000").json()["ticks"]) == 120
