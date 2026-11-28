"""Accepted review regressions; no provider/native calls."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import main
from app.lake import series_with_lake


def row(t):
    return dict(date=t, open=100.0, high=100.0, low=100.0, close=100.0, volume=1.0)


@pytest.mark.asyncio
async def test_lake_clips_timestamp_bounds_and_includes_date_end():
    class Lake:
        def wanted_days(self, *args):
            return [date(2026, 11, 23)]

        def read_day(self, *args):
            return pd.DataFrame(
                {
                    "time": [datetime(2026, 11, 23, h) for h in (10, 12, 13, 16)],
                    "price": [100.0] * 4,
                    "size": [1.0] * 4,
                }
            )

    bars, _ = await series_with_lake(
        "AAPL",
        "1m",
        "2026-11-23T12:00:00Z",
        "2026-11-23T13:00:00Z",
        None,
        timedelta(0),
        [],
        {},
        Lake(),
        today=date(2026, 11, 25),
    )
    assert [b["date"].hour for b in bars] == [12, 13]
    bars, _ = await series_with_lake(
        "AAPL",
        "1m",
        "2026-11-23",
        "2026-11-23",
        None,
        timedelta(0),
        [],
        {},
        Lake(),
        today=date(2026, 11, 25),
    )
    assert len(bars) == 4


@pytest.mark.asyncio
async def test_tick_start_clips_to_first_fully_covered_bucket(monkeypatch):
    import openbq_kdb.aggregate as agg

    ticks = [
        row(datetime(2026, 11, 25, 14, 30)),
        row(datetime(2026, 11, 25, 15, 1)),
        row(datetime(2026, 11, 25, 15, 3)),
    ]

    async def history(*args):
        return ticks, {}

    monkeypatch.setattr(main, "fetch_history", history)
    monkeypatch.setattr(
        agg,
        "aggregate_ticks",
        lambda store, sym, interval, lo, hi: [r for r in ticks if lo <= r["date"] <= hi],
    )
    recorder = SimpleNamespace(
        store=SimpleNamespace(tick_span=lambda sym: (ticks[0]["date"], ticks[-1]["date"]))
    )
    bars, _ = await main.build_series(
        "AAPL", "1m", "2026-11-25T15:00:30Z", "2026-11-25T15:02:00Z", recorder, timedelta(days=2)
    )
    assert [b["date"].minute for b in bars] == [1]


def test_socket_and_sector_share_account_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "2")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "watchlist.json"))

    class Seed:
        def get_live_stock_prices(self, **kwargs):
            return dict(close=100, previousClose=99, volume=1)

    app = main.create_app(api_key="fixture", seed_client=Seed())
    client = TestClient(app)
    assert client.post("/api/subscriptions", json={"symbol": "NVDA"}).status_code == 201
    assert client.post("/subscribe", json={"symbols": ["MSFT"]}).status_code == 200
    with client.websocket_connect("/live_grid_ws") as ws:
        ws.send_json({"params": {"symbol": "AAPL"}})
        for _ in range(30):
            state = client.get("/api/subscriptions").json()
            if state["used"] > 2:
                break
        assert state["used"] <= 2
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert client.get("/api/subscriptions").json()["used"] == 2
    assert client.get("/sector_map").status_code == 507
    with client.websocket_connect("/live_grid_ws") as ws:
        ws.send_json({"params": {"symbol": "NVDA"}})
        # A later HTTP request observes accepted registration on the same loop.
        assert client.get("/api/subscriptions").json()["used"] == 2
        ws.send_json({"params": {"symbol": "MSFT"}})
        assert client.get("/api/subscriptions").json()["used"] == 2


def test_sector_map_rejects_before_creating_over_budget_leases(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "2")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "watchlist.json"))
    client = TestClient(main.create_app(api_key="fixture", seed_client=object()))
    assert client.get("/sector_map").status_code == 507
    assert client.get("/api/subscriptions").json()["used"] == 0


def test_socket_replacement_releases_only_its_old_account_symbols(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "3")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "watchlist.json"))

    class Seed:
        def get_live_stock_prices(self, **kwargs):
            return dict(close=100, previousClose=99, volume=1)

    app = main.create_app(api_key="fixture", seed_client=Seed())
    client = TestClient(app)  # no lifespan/feed loop, no provider connection

    def observed(symbol):
        for _ in range(100):
            client.get("/api/subscriptions")
            if symbol in app.state.manager._union("us"):
                return
        pytest.fail(f"{symbol} was never admitted")

    client.post("/api/subscriptions", json={"symbol": "NVDA"})
    client.post("/subscribe", json={"symbols": ["MSFT"]})
    with client.websocket_connect("/live_grid_ws") as first:
        first.send_json({"params": {"symbol": "AAPL"}})
        observed("AAPL")
        with client.websocket_connect("/live_grid_ws") as second:
            second.send_json({"params": {"symbol": "GOOG"}})
            for _ in range(100):
                state = client.get("/api/subscriptions").json()
                if state["used"] > 3:
                    break
            assert state["used"] <= 3
            with pytest.raises(WebSocketDisconnect):
                second.receive_json()
        assert client.post("/subscribe", json={"symbols": ["GOOG"]}).status_code == 507
        assert client.post("/api/subscriptions", json={"symbol": "GOOG"}).status_code == 507
        first.send_json({"params": {"symbol": "TSLA"}})
        observed("TSLA")
        assert app.state.manager._union("us") == {"NVDA", "MSFT", "TSLA"}
    assert client.post("/api/subscriptions", json={"symbol": "GOOG"}).status_code == 201


def test_replacement_keeps_symbols_shared_with_another_active_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "4")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "watchlist.json"))

    class Seed:
        def get_live_stock_prices(self, **kwargs):
            return dict(close=100, previousClose=99, volume=1)

    app = main.create_app(api_key="fixture", seed_client=Seed())
    client = TestClient(app)
    assert client.post("/api/subscriptions", json={"symbol": "NVDA"}).status_code == 201
    assert client.post("/subscribe", json={"symbols": ["MSFT"]}).status_code == 200
    with client.websocket_connect("/live_grid_ws") as first:
        first.send_json({"params": {"symbol": "AAPL"}})
        with client.websocket_connect("/live_grid_ws") as second:
            second.send_json({"params": {"symbol": "AAPL,TSLA"}})
            for _ in range(100):
                state = client.get("/api/subscriptions").json()
                if state["used"] == 4:
                    break
            assert state["used"] == 4
            first.send_json({"params": {"symbol": "GOOG"}})
            for _ in range(100):
                state = client.get("/api/subscriptions").json()
                if state["used"] > 4:
                    break
            assert state["used"] == 4
            with pytest.raises(WebSocketDisconnect) as closed:
                first.receive_json()
            assert closed.value.code == 1008
            assert app.state.manager._union("us") == {"NVDA", "MSFT", "AAPL", "TSLA"}


@pytest.mark.asyncio
async def test_lake_end_clips_trades_inside_the_final_bucket():
    class Lake:
        def wanted_days(self, *args):
            return [date(2026, 11, 23)]

        def read_day(self, *args):
            return pd.DataFrame(
                {
                    "time": [datetime(2026, 11, 23, 12), datetime(2026, 11, 23, 12, 0, 45)],
                    "price": [100.0, 999.0],
                    "size": [1.0, 1.0],
                }
            )

    bars, _ = await series_with_lake(
        "AAPL",
        "1m",
        "2026-11-23T12:00:00Z",
        "2026-11-23T12:00:30Z",
        None,
        timedelta(0),
        [],
        {},
        Lake(),
        today=date(2026, 11, 25),
    )
    assert len(bars) == 1 and bars[0]["close"] == 100.0 and bars[0]["volume"] == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("tick_path", ["none", "empty", "gapfilled"])
async def test_history_and_gapfilled_rows_respect_utc_offset_bounds(monkeypatch, tick_path):
    """Removing the history clip or the bounded tick seam leaks adjacent minutes."""
    from app import gapfill
    import openbq_kdb.aggregate as aggregate

    history_rows = [row(f"2026-11-25T15:0{minute}:00Z") for minute in range(5)]

    async def history(*args):
        return history_rows, {}

    async def recent_minutes(*args):
        return [row(datetime(2026, 11, 25, 15, minute)) for minute in range(5)]

    monkeypatch.setattr(main, "fetch_history", history)
    monkeypatch.setattr(gapfill, "recent_minutes", recent_minutes)
    monkeypatch.setattr(aggregate, "aggregate_ticks", lambda *args: [])
    recorder = (
        None
        if tick_path == "none"
        else SimpleNamespace(
            store=SimpleNamespace(
                tick_span=lambda symbol: (datetime(2026, 11, 25, 15), datetime(2026, 11, 25, 15, 4))
            )
        )
    )
    bars, meta = await main.build_series(
        "AAPL",
        "1m",
        "2026-11-25T10:01:00-05:00",
        "2026-11-25T16:03:00+01:00",
        recorder,
        timedelta(days=2),
        gap_key="fixture" if tick_path == "gapfilled" else None,
    )
    expected = (
        ["2026-11-25T15:01:00Z", "2026-11-25T15:02:00Z", "2026-11-25T15:03:00Z"]
        if tick_path != "gapfilled"
        else ["2026-11-25T15:01:00Z", "2026-11-25T15:02:00Z"]
    )
    assert [main.wire_time(bar["date"]) for bar in bars] == expected
    if tick_path == "gapfilled":
        assert meta["rows_from_gapfill"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("history_rows", [[], [row("2026-11-24T15:00:00Z")]])
async def test_empty_lake_and_tick_results_clip_history(monkeypatch, history_rows):
    """A missing lake day and empty tick aggregate still honor the window."""
    import openbq_kdb.aggregate as aggregate

    class EmptyLake:
        def wanted_days(self, *args):
            return [date(2026, 11, 23)]

        def read_day(self, *args):
            return None

    monkeypatch.setattr(aggregate, "aggregate_ticks", lambda *args: [])
    recorder = SimpleNamespace(
        store=SimpleNamespace(
            tick_span=lambda symbol: (datetime(2026, 11, 23, 12), datetime(2026, 11, 23, 13))
        )
    )
    bars, _ = await series_with_lake(
        "AAPL",
        "1m",
        "2026-11-23T07:00:00-05:00",
        "2026-11-23T14:00:00+01:00",
        recorder,
        timedelta(days=2),
        history_rows,
        {},
        EmptyLake(),
        today=date(2026, 11, 25),
    )
    assert bars == []


@pytest.mark.asyncio
async def test_lake_selects_the_utc_day_for_an_offset_start(tmp_path, monkeypatch):
    """A positive offset can put the lower bound on the previous UTC day."""
    from app.lake import LakeTicks

    lake = LakeTicks(str(tmp_path), {})

    def read_day(symbol, day):
        if day == date(2026, 11, 23):
            return pd.DataFrame(
                {"time": [datetime(2026, 11, 23, 23)], "price": [100.0], "size": [1.0]}
            )
        return None

    monkeypatch.setattr(lake, "read_day", read_day)
    bars, _ = await series_with_lake(
        "AAPL",
        "1m",
        "2026-11-24T00:30:00+02:00",
        "2026-11-24T01:30:00+02:00",
        None,
        timedelta(0),
        [],
        {},
        lake,
        today=date(2026, 11, 25),
    )
    assert [bar["date"] for bar in bars] == [datetime(2026, 11, 23, 23)]
