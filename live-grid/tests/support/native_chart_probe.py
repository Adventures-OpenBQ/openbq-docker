"""Disposable real q -> owner-thread store -> live-grid -> real WebSocket probe."""

import asyncio
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

# Running this file directly puts support/, rather than live-grid/, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run():
    with tempfile.TemporaryDirectory(prefix="chart-native-") as temporary:
        root = Path(temporary)
        token = secrets.token_urlsafe(48)
        passwords = root / "passwords"
        passwords.write_text(f"host:{token}\n")
        passwords.chmod(0o600)
        client = root / "client-token"
        client.write_text(token)
        client.chmod(0o600)
        roles = root / "roles.json"
        roles.write_text(
            json.dumps(
                {"schema_version": 1, "principals": {"host": ["recorder", "chart", "diagnostics"]}}
            )
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        qport = listener.getsockname()[1]
        listener.close()
        q = os.environ["OPENBQ_TEST_Q"]
        env = dict(
            os.environ,
            KDB_AUTH_PASSWORDS_FILE=str(passwords),
            KDB_AUTH_ROLES_FILE=str(roles),
            QHOME=str(Path(q).parent.parent),
        )
        with (root / "q.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "openbq_kdb.bootstrap",
                    "--q",
                    q,
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(qport),
                    "--mode",
                    "tickplant",
                    "--data-dir",
                    str(root / "data"),
                ],
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(200):
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(log.read())
                    try:
                        with socket.create_connection(("127.0.0.1", qport), timeout=0.05):
                            break
                    except OSError:
                        time.sleep(0.02)
                else:
                    raise AssertionError("native q startup timed out")
                api_username = "native" + str(qport)
                api_password = secrets.token_urlsafe(24)
                os.environ.update(
                    KDB_USERNAME="host",
                    KDB_PASSWORD_FILE=str(client),
                    OPENBB_API_AUTH="true",
                    OPENBB_API_USERNAME=api_username,
                    **{"OPENBB_API_PASSWORD": api_password},
                    LIVE_GRID_CHART="false",
                    LIVE_GRID_CHART_STREAM="false",
                )
                asyncio.run(probe(qport))
                asyncio.run(probe_autowired_lifecycle(qport, root))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stdin.close()


async def probe(qport):
    import pandas as pd
    import httpx
    import uvicorn
    from websockets.asyncio.client import connect
    from openbq_kdb.config import KdbConfig
    from openbq_kdb.session import KdbSession
    from openbq_kdb.store import KdbStore
    from app.chart_stream_pump import StoreChartSource
    from app.chart_stream_protocol import validate
    from app.main import create_app

    cfg = KdbConfig(
        host=None,
        port=qport,
        bind_host="127.0.0.1",
        may_spawn=False,
        memory_mb=1024,
        watermark=0.75,
        upstream="eodhd",
        qhome="/not-used",
        qlic="/not-used",
        local_qhome="/not-used",
    )
    session = KdbSession(cfg)
    store = KdbStore(session)
    source = StoreChartSource(store)
    server = None
    server_task = None
    try:
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-11-20T14:30:31.000000001"]),
                "sym": ["AAPL"],
                "price": [100.0],
                "size": [2.0],
            }
        )
        assert await asyncio.to_thread(store.write_ticks, frame) == 1
        await source.qualify()
        app = create_app(api_key="synthetic-unused", chart_source=source)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient() as client:
            denied = await client.get(f"http://127.0.0.1:{port}/widgets.json")
            assert denied.status_code == 401
            response = await client.get(
                f"http://127.0.0.1:{port}/widgets.json",
                auth=(os.environ["OPENBB_API_USERNAME"], os.environ["OPENBB_API_PASSWORD"]),
            )
            widgets = response.json()
            assert widgets["live_chart"]["type"] == "live_chart"
            assert widgets["live_chart"]["extra_metadata"]["chart_stream_v1"] is True
            assert widgets["live_chart"]["wsEndpoint"] == "chart_stream_ws"
            assert widgets["ta_chart"]["wsEndpoint"] == "ta_chart_ws"
        view = {
            "symbol": "AAPL",
            "mode": "candles",
            "interval": "1m",
            "start": "2026-11-20T14:30:30.000000000Z",
            "max_items": 1,
        }
        credentials = os.environ["OPENBB_API_USERNAME"] + ":" + os.environ["OPENBB_API_PASSWORD"]
        headers = {"authorization": "Basic " + base64.b64encode(credentials.encode()).decode()}
        url = f"ws://127.0.0.1:{port}/chart_stream_ws"
        async with connect(url, additional_headers=headers) as ws:
            await ws.send(
                json.dumps(
                    dict(
                        protocol_version=1,
                        type="subscribe",
                        subscription_id="native",
                        request_id="one",
                        view=view,
                    )
                )
            )
            frames = [json.loads(await asyncio.wait_for(ws.recv(), 5)) for _ in range(3)]
            for value in frames:
                validate(value)
            begin, chunk, end = frames
            assert [f["type"] for f in frames] == [
                "snapshot_begin",
                "snapshot_chunk",
                "snapshot_end",
            ]
            assert chunk["items"][0]["volume"] == 2.0
            assert chunk["items"][0]["open"] == 100.0
            generation = begin["generation"]
            await ws.send(
                json.dumps(
                    dict(
                        protocol_version=1,
                        type="ack",
                        subscription_id="native",
                        generation=generation,
                        request_id="ack1",
                        cursor=end["cursor"],
                    )
                )
            )
            late = frame.copy()
            late["time"] = pd.to_datetime(["2026-11-20T14:30:30.000000000"])
            late["price"] = 90.0
            late["size"] = 3.0
            assert await asyncio.to_thread(store.write_ticks, late) == 1
            while True:
                change = json.loads(await asyncio.wait_for(ws.recv(), 5))
                validate(change)
                if change["type"] == "candles":
                    break
                assert change["type"] in ("candle_status", "heartbeat"), change
            assert change["candles"], (begin, chunk, change)
            candle = change["candles"][0]
            assert candle["open"] == 90.0 and candle["close"] == 100.0 and candle["volume"] == 5.0
            assert candle["tickCount"] == "2"
            await ws.send(
                json.dumps(
                    dict(
                        protocol_version=1,
                        type="ack",
                        subscription_id="native",
                        generation=generation,
                        request_id="ack2",
                        cursor=change["through_cursor"],
                    )
                )
            )
            checkpoint = {
                "cursor": change["through_cursor"],
                "view_key": begin["view_key"],
                "view_floor": begin["view_floor"],
                "retained_candle_keys": [candle["key"]],
            }
        async with connect(url, additional_headers=headers) as ws:
            await ws.send(
                json.dumps(
                    dict(
                        protocol_version=1,
                        type="resume",
                        subscription_id="native",
                        request_id="two",
                        view=view,
                        checkpoint=checkpoint,
                    )
                )
            )
            resumed = json.loads(await asyncio.wait_for(ws.recv(), 5))
            validate(resumed)
            assert resumed["type"] == "resumed", resumed
            assert resumed["generation"] != generation
            assert resumed["cursor"] == checkpoint["cursor"]
            assert resumed["view_floor"] == checkpoint["view_floor"]
            assert resumed["statuses"] == [{"key": candle["key"], "status": "closed"}]
        print("native chart snapshot, late replacement, and quiet resume passed")
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            await server_task
        await asyncio.to_thread(session.close)


async def probe_autowired_lifecycle(qport, root):
    import httpx
    import uvicorn
    from app.main import create_app

    os.environ.update(
        {
            "LIVE_GRID_CHART": "true",
            "LIVE_GRID_CHART_STREAM": "true",
            "LIVE_GRID_KDB_DIAGNOSTICS": "true",
            "LIVE_GRID_WATCHLIST": str(root / "watchlist.json"),
            "KDB_EMBEDDED": "false",
            "KDB_BIND_HOST": "127.0.0.1",
            "KDB_PORT": str(qport),
        }
    )
    app = create_app(api_key="synthetic-unused")
    owned = app.state.manager.recorder.store
    assert owned.session.secured
    assert app.state.chart_stream.source.source.store is owned
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    pump = None
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
                raise AssertionError("app startup failed")
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("app startup timed out")
        assert app.state.chart_stream.source.qualified
        pump = app.state.kdb_diagnostics
        assert pump.store is owned
        for _ in range(200):
            if pump.cursor > 0:
                break
            await asyncio.sleep(0.01)
        assert pump.cursor > 0 and pump.failures == 0
        async with httpx.AsyncClient(
            auth=(os.environ["OPENBB_API_USERNAME"], os.environ["OPENBB_API_PASSWORD"])
        ) as client:
            widgets = (await client.get(f"http://127.0.0.1:{port}/widgets.json")).json()
            assert widgets["live_chart"]["extra_metadata"]["chart_stream_v1"] is True
            assert widgets["live_chart"]["wsEndpoint"] == "chart_stream_ws"
            health = (await client.get(f"http://127.0.0.1:{port}/health")).json()
            assert health["kdb_diagnostics"]["enabled"] is True
            assert health["kdb_diagnostics"]["failures"] == 0
            assert set(health["kdb_diagnostics"]) == {
                "enabled",
                "dropped",
                "pending",
                "overwritten",
                "failures",
            }
    finally:
        server.should_exit = True
        started = time.monotonic()
        await asyncio.wait_for(task, 3)
        assert time.monotonic() - started < 2
        if pump:
            assert pump._stop.is_set()
            assert not pump._poller.is_alive() and not pump._worker.is_alive()
        await asyncio.to_thread(owned.session.close)
    print("native autowired chart and diagnostics lifecycle passed")


if __name__ == "__main__":
    run()
