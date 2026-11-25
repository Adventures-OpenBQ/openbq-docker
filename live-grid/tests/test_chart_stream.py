import json
from pathlib import Path
import pytest
from app.chart_stream_protocol import normalize_view, view_key, validate, wire

FIXTURES = json.loads(
    (Path(__file__).parents[1] / "app/resources/chart-stream-v1.examples.json").read_text()
)


def test_frozen_transcripts_and_hashes():
    for transcript in FIXTURES:
        for frame in transcript["frames"]:
            validate(frame)
            if "view_key" in frame:
                assert view_key(frame["view"]) == frame["view_key"]


def test_normalization_and_sequence_precision():
    assert normalize_view({"symbol": "AAPL", "mode": "ticks", "start": "2026-11-20T14:30:00Z"})[
        "start"
    ].endswith(".000000000Z")
    assert wire({b"seq": b"9007199254740993"}) == {"seq": "9007199254740993"}
    frame = dict(FIXTURES[0]["frames"][4], cursor={"epoch": "a", "seq": str(2**63)})
    with pytest.raises(ValueError):
        validate(frame)


@pytest.mark.asyncio
async def test_snapshot_pump_reads_changes_before_transport_send():
    from app.chart_stream_pump import ChartPump

    source = Source()
    snapshot, changes = await ChartPump(
        source, {"symbol": "AAPL", "mode": "ticks", "start": "2026-11-20T14:30:00Z"}
    ).admit()
    assert source.calls == ["snapshot", "changes"]
    assert snapshot["cursor"]["seq"] == "9007199254740993"
    assert changes["through_cursor"]["seq"] == "9007199254740994"


class Source:
    qualified = True

    def __init__(self):
        self.calls = []

    async def snapshot(self, view):
        self.calls.append("snapshot")
        begin = FIXTURES[0]["frames"][1]
        return {k: begin[k] for k in ("cursor", "view_floor", "coverage", "truncated")} | {
            "items": FIXTURES[0]["frames"][2]["items"]
        }

    async def changes(self, cursor, view):
        self.calls.append("changes")
        frame = FIXTURES[0]["frames"][5]
        if cursor == frame["through_cursor"]:
            return {"from_cursor": cursor, "through_cursor": cursor, "batches": []}
        return {k: frame[k] for k in ("from_cursor", "through_cursor", "batches")}

    async def status(self):
        return {
            "current_cursor": {"epoch": "epoch-a", "seq": "9007199254740994"},
            "coverage": FIXTURES[0]["frames"][1]["coverage"],
            "clock": "2026-11-20T14:32:00.000000000Z",
        }


@pytest.fixture
def chart_app(monkeypatch):
    monkeypatch.setenv("OPENBB_API_AUTH", "true")
    monkeypatch.setenv("OPENBB_API_USERNAME", "test")
    monkeypatch.setenv("OPENBB_API_PASSWORD", "secret")
    from fastapi import FastAPI
    from app.chart_stream import attach_chart_stream

    app = FastAPI()
    attach_chart_stream(app, Source())
    return app


def test_socket_auth_snapshot_ack_and_cleanup(chart_app):
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    with TestClient(chart_app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/chart_stream_ws"):
                pass
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            ws.send_json(FIXTURES[0]["frames"][0])
            frames = [ws.receive_json() for _ in range(4)]
            assert [f["type"] for f in frames] == [
                "snapshot_begin",
                "snapshot_chunk",
                "snapshot_end",
                "ticks",
            ]
            for frame in frames:
                validate(frame)
            generation = frames[0]["generation"]
            ws.send_json(
                dict(
                    FIXTURES[0]["frames"][4],
                    generation=generation,
                    cursor=frames[-1]["through_cursor"],
                )
            )
            ws.send_json(
                dict(
                    protocol_version=1,
                    type="unsubscribe",
                    subscription_id="aapl",
                    generation=generation,
                    request_id="stop",
                )
            )
            assert ws.receive_json()["type"] == "unsubscribed"
    assert chart_app.state.chart_stream.pending_bytes == 0
    assert chart_app.state.chart_stream.connections == 0


def test_resume_rejects_wrong_view(chart_app):
    from starlette.testclient import TestClient

    with TestClient(chart_app) as client:
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            resume = json.loads(json.dumps(FIXTURES[0]["frames"][6]))
            resume["checkpoint"]["view_key"] = "0" * 64
            ws.send_json(resume)
            assert ws.receive_json()["reason"] == "view_mismatch"


@pytest.mark.asyncio
async def test_quiet_candle_status_uses_source_clock(chart_app):
    from app.chart_stream import Connection

    conn = Connection(chart_app.state.chart_stream, None)
    key = FIXTURES[1]["frames"][1]["items"][0]["key"]
    assert await conn.statuses({}, [key]) == [{"key": key, "status": "closed"}]


@pytest.mark.asyncio
async def test_real_tcp_socket_snapshot_ack_and_stale_generation(chart_app):
    import asyncio
    import socket
    import uvicorn
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(chart_app, log_level="critical", lifespan="off", ws_max_size=65536)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        async with connect(
            f"ws://127.0.0.1:{port}/chart_stream_ws",
            additional_headers={"authorization": "Basic dGVzdDpzZWNyZXQ="},
        ) as ws:
            await ws.send(json.dumps(FIXTURES[0]["frames"][0]))
            frames = [json.loads(await ws.recv()) for _ in range(4)]
            assert frames[-1]["through_cursor"]["seq"] == "9007199254740994"
            ack = dict(FIXTURES[0]["frames"][4], generation="stale")
            await ws.send(json.dumps(ack))
            with pytest.raises(ConnectionClosed) as exc:
                await ws.recv()
            assert exc.value.rcvd.code == 1008
    finally:
        server.should_exit = True
        await task
    assert chart_app.state.chart_stream.pending_bytes == 0


@pytest.mark.asyncio
async def test_unacknowledged_bytes_count_until_applied_ack(chart_app):
    from app.chart_stream import Connection, Overloaded, CONNECTION_BYTES, PROCESS_BYTES

    conn = Connection(chart_app.state.chart_stream, None)
    frame = FIXTURES[0]["frames"][5]
    conn.enqueue(frame, cursor=frame["through_cursor"])
    entry = conn.pending[0]
    entry["sent"] = True
    assert conn.bytes == entry["size"] > 0
    assert conn.service.pending_bytes == conn.bytes
    conn.bytes = CONNECTION_BYTES
    with pytest.raises(Overloaded):
        conn.enqueue(frame, cursor=frame["through_cursor"])
    conn.bytes = entry["size"]
    conn.service.pending_bytes = PROCESS_BYTES
    with pytest.raises(Overloaded):
        conn.enqueue(frame, cursor=frame["through_cursor"])
    conn.service.pending_bytes = entry["size"]
    conn.release(entry)
    assert conn.bytes == conn.service.pending_bytes == 0


@pytest.mark.asyncio
async def test_store_source_requires_full_named_capability_qualification():
    from app.chart_stream_pump import StoreChartSource

    class Store:
        class session:
            capabilities = frozenset({"streamStatus"})

        def stream_status(self):
            return {
                "current_cursor": {"epoch": "a", "seq": "0"},
                "clock": "2026-11-20T14:32:00.000000000Z",
            }

    store = Store()
    source = StoreChartSource(store)
    with pytest.raises(ValueError):
        await source.qualify()
    assert not source.qualified
    store.session.capabilities = frozenset(source.REQUIRED)
    await source.qualify()
    assert source.qualified


@pytest.mark.asyncio
async def test_slow_snapshot_send_does_not_stop_retention_reads(chart_app):
    import asyncio
    from app.chart_stream import Connection

    class Socket:
        headers = {"authorization": "Basic dGVzdDpzZWNyZXQ="}

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def send_text(self, text):
            self.started.set()
            await self.release.wait()

        async def close(self, code):
            pass

    socket = Socket()
    conn = Connection(chart_app.state.chart_stream, socket)
    sub = dict(
        sid="a",
        generation="g",
        view=normalize_view(FIXTURES[0]["frames"][0]["view"]),
        active=True,
        alive=__import__("time").monotonic(),
        status_seq=0,
        keys=[],
        statuses=[],
    )
    producer = asyncio.create_task(conn.produce(sub, None))
    sender = asyncio.create_task(conn.sender())
    conn.tasks.update((producer, sender))
    try:
        await asyncio.wait_for(socket.started.wait(), 1)
        await asyncio.sleep(0.25)
        assert chart_app.state.chart_stream.source.calls.count("changes") >= 3
        assert conn.bytes > 0  # includes blocked snapshot and staged catch-up
    finally:
        await conn.cleanup()
    assert conn.service.pending_bytes == 0


@pytest.mark.asyncio
async def test_progress_timeout_resets_real_socket(chart_app, monkeypatch):
    import asyncio
    import socket
    import uvicorn
    from websockets.asyncio.client import connect
    import app.chart_stream as stream

    monkeypatch.setattr(stream, "PROGRESS_SECONDS", 0.15)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(chart_app, log_level="critical", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        async with connect(
            f"ws://127.0.0.1:{sock.getsockname()[1]}/chart_stream_ws",
            additional_headers={"authorization": "Basic dGVzdDpzZWNyZXQ="},
        ) as ws:
            await ws.send(json.dumps(FIXTURES[0]["frames"][0]))
            frames = [json.loads(await asyncio.wait_for(ws.recv(), 1)) for _ in range(5)]
            assert frames[-1]["type"] == "resync_required"
            assert frames[-1]["reason"] == "slow_consumer"
    finally:
        server.should_exit = True
        await task
    assert chart_app.state.chart_stream.pending_bytes == 0


def test_manifest_advertises_only_qualified_chart_source(monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    monkeypatch.setenv("LIVE_GRID_CHART_STREAM", "false")
    monkeypatch.setenv("OPENBB_API_AUTH", "false")
    from app.main import create_app
    from starlette.testclient import TestClient

    legacy = TestClient(create_app(api_key="test")).get("/widgets.json").json()["live_chart"]
    assert not legacy.get("extra_metadata", {}).get("chart_stream_v1")
    source = Source()
    qualified = (
        TestClient(create_app(api_key="test", chart_source=source))
        .get("/widgets.json")
        .json()["live_chart"]
    )
    assert qualified["extra_metadata"]["chart_stream_v1"] is True
    assert qualified["wsEndpoint"] == "chart_stream_ws"
    assert qualified["type"] == "live_chart"
    legacy_ta = (
        TestClient(create_app(api_key="test", chart_source=source))
        .get("/widgets.json")
        .json()["ta_chart"]
    )
    assert legacy_ta["wsEndpoint"] == "ta_chart_ws"
    assert not legacy_ta.get("extra_metadata", {}).get("chart_stream_v1")
    source.qualified = False
    pending = (
        TestClient(create_app(api_key="test", chart_source=source))
        .get("/widgets.json")
        .json()["live_chart"]
    )
    assert not pending.get("extra_metadata", {}).get("chart_stream_v1")


@pytest.mark.asyncio
async def test_identical_views_share_inflight_and_completed_native_reads():
    import asyncio
    from app.chart_stream_pump import SharedChartSource

    class Delayed(Source):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()

        async def snapshot(self, view):
            self.calls.append("started")
            await self.gate.wait()
            return await super().snapshot(view)

    source = Delayed()
    shared = SharedChartSource(source)
    view = FIXTURES[0]["frames"][0]["view"]
    a = asyncio.create_task(shared.snapshot(view))
    b = asyncio.create_task(shared.snapshot(dict(view)))
    await asyncio.sleep(0.01)
    assert source.calls == ["started"]
    source.gate.set()
    assert await a == await b
    await shared.snapshot(view)
    assert source.calls.count("snapshot") == 1
    assert shared.cache_bytes > 0
    await asyncio.sleep(0.06)
    assert shared.cache_bytes == 0
    await shared.close()
    assert not shared.inflight and not shared.cache


def test_quiet_snapshot_ack_has_no_redundant_unsent_cursor_frame(chart_app):
    from starlette.testclient import TestClient

    class Quiet(Source):
        async def changes(self, cursor, view):
            return {"from_cursor": cursor, "through_cursor": cursor, "batches": []}

    chart_app.state.chart_stream.source.source = Quiet()
    with TestClient(chart_app) as client:
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            ws.send_json(FIXTURES[0]["frames"][0])
            frames = [ws.receive_json() for _ in range(3)]
            assert frames[-1]["type"] == "snapshot_end"
            generation = frames[-1]["generation"]
            ws.send_json(dict(FIXTURES[0]["frames"][4], generation=generation))
            ws.send_json(
                dict(
                    protocol_version=1,
                    type="unsubscribe",
                    subscription_id="aapl",
                    generation=generation,
                    request_id="end",
                )
            )
            assert ws.receive_json()["type"] == "unsubscribed"


def test_backward_applied_ack_is_rejected_and_duplicates_are_allowed(chart_app):
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    with TestClient(chart_app) as client:
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            ws.send_json(FIXTURES[0]["frames"][0])
            frames = [ws.receive_json() for _ in range(4)]
            ack = dict(
                FIXTURES[0]["frames"][4],
                generation=frames[-1]["generation"],
                cursor=frames[-1]["through_cursor"],
            )
            ws.send_json(ack)
            ws.send_json(ack)
            ws.send_json(dict(ack, cursor=frames[0]["cursor"]))
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1008


def test_quiet_candle_resume_has_authoritative_status_baseline(chart_app):
    from starlette.testclient import TestClient

    class CandleSource(Source):
        async def changes(self, cursor, view):
            return {"from_cursor": cursor, "through_cursor": cursor, "candles": []}

    chart_app.state.chart_stream.source.source = CandleSource()
    resume = FIXTURES[1]["frames"][5]
    with TestClient(chart_app) as client:
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            ws.send_json(resume)
            resumed = ws.receive_json()
            assert resumed["type"] == "resumed"
            assert resumed["view_floor"] == resume["checkpoint"]["view_floor"]
            assert resumed["cursor"] == resume["checkpoint"]["cursor"]
            assert resumed["generation"] != "generation-a"
            assert resumed["status_seq"] == "0"
            assert resumed["statuses"] == FIXTURES[1]["frames"][6]["statuses"]
            validate(resumed)


@pytest.mark.asyncio
async def test_irrelevant_unavailable_candle_buckets_do_not_force_reset():
    from app.chart_stream_pump import ChartPump

    class CandleSource(Source):
        async def changes(self, cursor, view):
            return {
                "from_cursor": cursor,
                "through_cursor": cursor,
                "candles": [],
                "unavailable_buckets": [{"bucket_start": "2026-11-20T14:29:00.000000000Z"}],
            }

    pump = ChartPump(CandleSource(), FIXTURES[1]["frames"][0]["view"])
    pump.cursor = FIXTURES[1]["frames"][0]["cursor"]
    pump.floor = FIXTURES[1]["frames"][0]["view_floor"]
    assert "reason" not in await pump.poll()


def test_mid_bucket_candle_resume_accepts_retained_bucket_floor(chart_app):
    from starlette.testclient import TestClient

    class CandleSource(Source):
        async def changes(self, cursor, view):
            return {"from_cursor": cursor, "through_cursor": cursor, "candles": []}

    chart_app.state.chart_stream.source.source = CandleSource()
    resume = json.loads(json.dumps(FIXTURES[1]["frames"][5]))
    resume["view"]["start"] = "2026-11-20T14:30:30.000000000Z"
    resume["checkpoint"]["view_key"] = view_key(resume["view"])
    with TestClient(chart_app) as client:
        with client.websocket_connect(
            "/chart_stream_ws", headers={"authorization": "Basic dGVzdDpzZWNyZXQ="}
        ) as ws:
            ws.send_json(resume)
            resumed = ws.receive_json()
            assert resumed["type"] == "resumed"
            assert resumed["view_floor"] == resume["checkpoint"]["view_floor"]


@pytest.mark.asyncio
async def test_rolling_candle_floor_advances_pump_coverage_filter(chart_app):
    import asyncio
    from app.chart_stream import Connection

    initial = json.loads(json.dumps(FIXTURES[1]["frames"][0]))
    candle_a = json.loads(json.dumps(FIXTURES[1]["frames"][1]["items"][0]))
    candle_b = json.loads(json.dumps(candle_a))
    candle_b["key"]["bucket_start"] = "2026-11-20T14:31:00.000000000Z"
    candle_b["revision"]["seq"] = "9007199254740994"

    class Rolling(Source):
        def __init__(self):
            super().__init__()
            self.read = asyncio.Event()

        async def snapshot(self, view):
            return {k: initial[k] for k in ("cursor", "view_floor", "coverage", "truncated")} | {
                "items": [candle_a]
            }

        async def changes(self, cursor, view):
            if cursor["seq"] == "9007199254740993":
                return {
                    "from_cursor": cursor,
                    "through_cursor": candle_b["revision"],
                    "candles": [candle_b],
                }
            self.read.set()
            return {
                "from_cursor": cursor,
                "through_cursor": cursor,
                "candles": [],
                "unavailable_buckets": [candle_a["key"]],
            }

    class Socket:
        headers = {"authorization": "Basic dGVzdDpzZWNyZXQ="}

        async def close(self, code):
            raise AssertionError(code)

    source = Rolling()
    chart_app.state.chart_stream.source.source = source
    connection = Connection(chart_app.state.chart_stream, Socket())
    view = normalize_view(initial["view"] | {"max_items": 1})
    sub = dict(
        sid="a",
        generation="g",
        view=view,
        active=True,
        alive=__import__("time").monotonic(),
        status_seq=0,
        keys=[],
        statuses=[],
    )
    producer = asyncio.create_task(connection.produce(sub, None))
    connection.tasks.add(producer)
    try:
        await asyncio.wait_for(source.read.wait(), 1)
        await asyncio.sleep(0.01)
        assert sub["floor"]["bucket_start"] == candle_b["key"]["bucket_start"]
        assert all(
            json.loads(entry["text"])["type"] != "resync_required"
            for entry in connection.pending
            if entry["text"]
        )
    finally:
        await connection.cleanup()


def test_secured_optin_invalid_credentials_fail_before_feed_start(monkeypatch):
    from app.main import create_app
    import openbq_kdb.session

    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("LIVE_GRID_CHART_STREAM", "true")
    monkeypatch.setenv("KDB_USERNAME", "synthetic")
    monkeypatch.setenv("KDB_PASSWORD_FILE", "/synthetic/missing-secret")

    def invalid(_config):
        raise ValueError("private credential file detail")

    monkeypatch.setattr(openbq_kdb.session, "KdbSession", invalid)

    def feed_must_not_start(*args, **kwargs):
        raise AssertionError("feed constructed after credential failure")

    monkeypatch.setattr("app.main.FeedManager", feed_must_not_start)
    with pytest.raises(
        RuntimeError, match="secured chart source configuration unavailable"
    ) as error:
        create_app(api_key="synthetic")
    assert "private credential" not in str(error.value)
