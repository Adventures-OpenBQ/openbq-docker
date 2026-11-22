"""Diagnostics is opt-in, shares the owned secured store, and shuts down boundedly."""

import asyncio
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def lifecycle(monkeypatch, tmp_path):
    from app.main import create_app
    import openbq_kdb.session
    import openbq_kdb.store
    import app.recorder

    events = []
    instances = []

    class Session:
        secured = True
        endpoint = None

        def __init__(self, config):
            pass

    class Store:
        def __init__(self, session):
            self.session = session

    class Recorder:
        def __init__(self, store, **kwargs):
            self.store = store

        def record(self, *args):
            pass

        def stats(self):
            return {}

        def stash(self):
            events.append("stash")

    class Pump:
        dropped = 2
        pending = 3
        overwritten = 4
        failures = 5

        def __init__(self, store):
            self.store = store
            instances.append(self)

        def start(self):
            events.append("start")
            return self

        def close(self, timeout):
            events.append(("close", timeout))

    async def idle(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(openbq_kdb.session, "KdbSession", Session)
    monkeypatch.setattr(openbq_kdb.store, "KdbStore", Store)
    monkeypatch.setattr(app.recorder, "TickRecorder", Recorder)
    monkeypatch.setattr("app.main.FeedManager.run", idle)
    monkeypatch.setitem(sys.modules, "openbq_kdb.diagnostics", SimpleNamespace(DiagnosticPump=Pump))
    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("LIVE_GRID_CHART_STREAM", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "empty-watchlist.json"))
    return create_app, Session, events, instances


def test_diagnostic_pump_uses_owned_store_and_closes_after_stash(monkeypatch, lifecycle):
    from starlette.testclient import TestClient

    create_app, _, events, instances = lifecycle
    monkeypatch.setenv("LIVE_GRID_KDB_DIAGNOSTICS", "true")
    app = create_app(api_key="synthetic")
    with TestClient(app) as client:
        assert events == ["start"]
        assert instances[0].store is app.state.manager.recorder.store
        assert client.get("/health").json()["kdb_diagnostics"] == {
            "enabled": True,
            "dropped": 2,
            "pending": 3,
            "overwritten": 4,
            "failures": 5,
        }
    assert events == ["start", "stash", ("close", 0.5)]


@pytest.mark.parametrize("enabled,secured", [("false", True), ("true", False)])
def test_diagnostics_never_starts_implicitly_or_on_legacy_source(
    monkeypatch, lifecycle, enabled, secured
):
    from starlette.testclient import TestClient

    create_app, session, events, instances = lifecycle
    session.secured = secured
    monkeypatch.setenv("LIVE_GRID_KDB_DIAGNOSTICS", enabled)
    with TestClient(create_app(api_key="synthetic")) as client:
        assert "kdb_diagnostics" not in client.get("/health").json()
        assert instances == []
    assert events == ["stash"]
