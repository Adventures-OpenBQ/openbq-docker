# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""scripts/eod_dump.py and scripts/s3_init.py against an S3 fake (moto), no docker.

The store is a moto S3 server on 127.0.0.1 spoken to with the same DELTA_S3_*
contract rustfs.env carries for RustFS (plain HTTP, path-style, conditional
put). The ticks are synthetic. kdb is never contacted: `read_day` is replaced
by a frame, and `_stage_day` runs against a fake `pykx` module.

Run in the lake environment (openbb-deltalake + deltalake + pyarrow + moto +
openbq-kdb); see docs/v10/live-grid-kdb-port.md for the receipt.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 10, 9)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def s3():
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield host, port
    server.stop()


@pytest.fixture
def store_env(s3, monkeypatch):
    host, port = s3
    bucket = "openbq-" + datetime.now().strftime("%H%M%S%f")
    env = {"DELTA_S3_ENDPOINT": host, "DELTA_S3_PORT": str(port), "DELTA_S3_SECURE": "false",
           "DELTA_S3_BUCKET": bucket, "DELTA_S3_ACCESS": "EXAMPLE_ACCESS", "DELTA_S3_SECRET": "EXAMPLE_SECRET"}
    for key in [k for k in list(__import__("os").environ) if k.startswith(("DELTA_", "LAKE_", "EOD_"))]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def _ticks():
    rows = []
    t0 = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=14, minutes=30)
    for i in range(40):
        rows.append((t0 + timedelta(seconds=7 * i), "AAPL", 100.0 + i % 5, 1.0))
    for i in range(25):
        rows.append((t0 + timedelta(seconds=11 * i), "BTC-USD", 60000.0 + i, 0.01))
    return pd.DataFrame(rows, columns=["time", "sym", "price", "size"])


# -- s3_init ---------------------------------------------------------------------

def test_s3_init_creates_the_bucket_once_and_is_idempotent(store_env):
    s3_init = _load("s3_init")
    cfg = s3_init.settings()
    assert cfg["endpoint"].startswith("http://127.0.0.1:")
    assert s3_init.ensure_bucket(cfg) is True
    assert s3_init.ensure_bucket(cfg) is False
    assert s3_init.main(attempts=1, delay=0) == 0


def test_s3_init_refuses_without_the_contract(monkeypatch):
    s3_init = _load("s3_init")
    for key in ("DELTA_S3_ENDPOINT", "DELTA_S3_BUCKET", "DELTA_S3_ACCESS", "DELTA_S3_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert s3_init.main(attempts=1, delay=0) == 2
    with pytest.raises(ValueError, match="DELTA_S3_ACCESS"):
        s3_init.settings({"DELTA_S3_ENDPOINT": "rustfs", "DELTA_S3_BUCKET": "openbq"})


def test_s3_init_gives_up_when_the_store_never_answers(store_env, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed = sock.getsockname()[1]
    monkeypatch.setenv("DELTA_S3_PORT", str(closed))
    assert _load("s3_init").main(attempts=2, delay=0) == 1


def test_s3_init_uses_no_minio_client():
    text = (ROOT / "scripts" / "s3_init.py").read_text()
    assert "mc " not in text.replace("`mc mb", "") and "import minio" not in text


# -- eod_dump ----------------------------------------------------------------------

def test_the_flush_writes_one_delta_table_per_symbol_and_day_and_reads_back(store_env, monkeypatch):
    _load("s3_init").main(attempts=1, delay=0)
    eod = _load("eod_dump")
    monkeypatch.setattr(eod, "read_day", lambda day: _ticks())
    assert eod.dump_day(DAY) == 65

    from openbb_deltalake import store

    s = store(layer="silver", library="ticks_live")
    assert s.base == f"s3://{store_env['DELTA_S3_BUCKET']}"
    assert sorted(s.list_symbols()) == ["AAPL_2026_10_09", "BTC_USD_2026_10_09"]
    from deltalake import DeltaTable

    # DeltaTable directly, not s.read(): store.read() asks has(), i.e.
    # DeltaTable.is_deltatable, which never returned against an S3 endpoint in
    # this environment (deltalake 1.6.6 and 1.1.4, moto); recorded in the ledger.
    back = DeltaTable(s._path("AAPL_2026_10_09"), storage_options=s.storage_options).to_pandas()
    assert len(back) == 40 and {"date", "price", "size"} <= set(back.columns)

    # idempotent: a re-run overwrites (a new Delta version), it never duplicates
    assert eod.dump_day(DAY) == 65

    table = DeltaTable(s._path("AAPL_2026_10_09"), storage_options=s.storage_options)
    assert table.version() == 1 and len(table.to_pandas()) == 40

    # live-grid's read-back reads exactly what the flush wrote
    sys.path.insert(0, str(ROOT / "live-grid"))
    try:
        from app.lake import LakeTicks, bars
    finally:
        sys.path.remove(str(ROOT / "live-grid"))
    reader = LakeTicks.from_env(dict(store_env, LIVE_GRID_LAKE_READBACK="true"))
    got = reader.read_day("BTC-USD", DAY)
    assert len(got) == 25 and got["time"].is_monotonic_increasing
    assert reader.read_day("AAPL", DAY - timedelta(days=1)) is None
    assert len(bars(got, "1m")) == 5


def test_a_catch_up_never_overwrites_a_complete_day_with_a_partial_one(store_env, monkeypatch):
    """D3 (2026-10-16): a restart's catch-up re-reads a day kdb has partly pruned. The stored
    table already holds more rows from an earlier start, so it is kept; a fuller frame still
    replaces it."""
    _load("s3_init").main(attempts=1, delay=0)
    eod = _load("eod_dump")
    full = _ticks()
    monkeypatch.setattr(eod, "read_day", lambda day: full)
    assert eod.dump_day(DAY) == 65
    from deltalake import DeltaTable
    from openbb_deltalake import store

    s = store(layer="silver", library="ticks_live")
    path = s._path("AAPL_2026_10_09")
    # kdb now holds only the later part of the day (the prune took the start)
    tail = full.groupby("sym", observed=True).tail(10).reset_index(drop=True)
    monkeypatch.setattr(eod, "read_day", lambda day: tail)
    assert eod.dump_day(DAY) == 0
    table = DeltaTable(path, storage_options=s.storage_options)
    assert table.version() == 0 and len(table.to_pandas()) == 40
    # a frame with more ticks (a late print kdb received) does replace the table
    extra = pd.concat([full, full.tail(1).assign(price=1.0)], ignore_index=True)
    monkeypatch.setattr(eod, "read_day", lambda day: extra)
    assert eod.dump_day(DAY) == 66
    assert DeltaTable(path, storage_options=s.storage_options).version() == 1


def test_the_tick_window_outlives_the_flush_and_every_retry():
    """D3: live-grid prunes kdb to LIVE_TICK_WINDOW_SECONDS. The window must still hold the
    whole UTC day at 00:05 and at the last hourly retry, or every flush loses the day's start."""
    import yaml

    eod = _load("eod_dump")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    window = int(compose["services"]["live-grid"]["environment"]["LIVE_TICK_WINDOW_SECONDS"])
    prune_lag = 60  # live-grid's prune cadence (feeds.py)
    last_read = 86400 + eod.FLUSH_UTC_MINUTES * 60 + eod.RETRY_ATTEMPTS * eod.RETRY_SLEEP_S
    assert window >= last_read + prune_lag


def test_the_flush_writes_only_the_durable_copy_by_default(store_env, monkeypatch):
    _load("s3_init").main(attempts=1, delay=0)
    eod = _load("eod_dump")
    assert eod.HOT_SESSIONS == 0 and eod.LIBRARY == "ticks_live" and eod.LAYER == "silver"
    monkeypatch.setattr(eod, "read_day", lambda day: _ticks())
    eod.dump_day(DAY)
    from openbb_deltalake import store

    assert store(layer="silver_hot", library="ticks_live_recent").list_symbols() == []


def test_a_dry_run_and_an_empty_day_write_nothing(store_env, monkeypatch):
    _load("s3_init").main(attempts=1, delay=0)
    eod = _load("eod_dump")
    monkeypatch.setattr(eod, "read_day", lambda day: _ticks())
    assert eod.dump_day(DAY, dry_run=True) == 65
    monkeypatch.setattr(eod, "read_day", lambda day: _ticks().iloc[0:0])
    assert eod.dump_day(DAY) == 0
    from openbb_deltalake import store

    assert store(layer="silver", library="ticks_live").list_symbols() == []


def test_the_flush_refuses_to_write_without_the_store(monkeypatch):
    eod = _load("eod_dump")
    for key in ("DELTA_S3_ENDPOINT", "DELTA_S3_BUCKET", "DELTA_S3_ACCESS", "DELTA_S3_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DELTA_URI", "/tmp/never-used")  # layer writes ignore DELTA_URI
    assert eod.store_configured() is False
    monkeypatch.setattr(sys, "argv", ["eod_dump.py", "--date", "2026-10-09"])
    with pytest.raises(SystemExit) as exit_:
        eod.main()
    assert exit_.value.code == 2


def test_the_flush_reads_kdb_over_ipc_only(monkeypatch):
    eod = _load("eod_dump")
    monkeypatch.setenv("KDB_HTTP_URL", "http://kdb.example:5999")
    monkeypatch.setattr(eod, "_read_day_ipc", lambda day: "ipc")
    assert eod.read_day(DAY) == "ipc"
    assert not hasattr(eod, "_read_day_http")


def test_stage_day_reads_the_utc_day_over_ipc_in_chunks(tmp_path, monkeypatch):
    calls = []
    frame = _ticks()

    class Conn:
        def __init__(self, host, port):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __call__(self, query, *args):
            calls.append((query.split("]")[0], args))
            if "exec count i" in query:
                return types.SimpleNamespace(py=lambda: len(frame))
            offset, n = args[2], args[3]
            return types.SimpleNamespace(pd=lambda: frame.iloc[offset:offset + n])

    fake = types.SimpleNamespace(
        SyncQConnection=lambda host, port: Conn(host, port),
        TimestampAtom=object, toq=lambda value, kind: value)
    monkeypatch.setitem(sys.modules, "pykx", fake)
    monkeypatch.setenv("KDB_HOST", "kdb")
    monkeypatch.setenv("KDB_PORT", "5000")
    eod = _load("eod_dump")
    out = tmp_path / "day.parquet"
    eod._stage_day(DAY, str(out))
    assert calls[0] == ("connect", "kdb", 5000)
    start, end = calls[1][1]
    assert start == datetime(2026, 10, 9) and end == datetime(2026, 10, 10)
    assert len(pd.read_parquet(out)) == 65


def test_the_flushed_layout_reads_back_through_openbb_deltalake_on_a_local_store(tmp_path, monkeypatch):
    """The donor's own read path (store.read, has()) over the same layout, local."""
    for key in [k for k in list(__import__("os").environ) if k.startswith(("DELTA_", "LAKE_"))]:
        monkeypatch.delenv(key, raising=False)
    eod = _load("eod_dump")
    monkeypatch.setattr(eod, "read_day", lambda day: _ticks())
    from openbb_deltalake import store

    monkeypatch.setattr("openbb_deltalake.utils.default_base", lambda: str(tmp_path))
    assert eod.dump_day(DAY) == 65
    s = store(layer="silver", library="ticks_live")
    assert s.base == str(tmp_path) and s.has("AAPL_2026_10_09")
    back = s.read("AAPL_2026_10_09", output="dataframe")
    assert len(back) == 40 and back.index.is_monotonic_increasing


# -- the S3 feature Delta commits rely on -------------------------------------------

def test_the_store_contract_asks_for_conditional_put_and_path_style(store_env):
    from openbb_deltalake.utils import s3_options_from_env

    base, opts = s3_options_from_env()
    assert opts["aws_conditional_put"] == "etag"
    assert opts["aws_virtual_hosted_style_request"] == "false"
    assert opts["aws_allow_http"] == "true"


def test_a_second_commit_of_the_same_version_is_refused_with_412(store_env):
    """What aws_conditional_put=etag relies on: put-if-absent on _delta_log entries.
    moto enforces it; RustFS is Mac-pending (docs/v10/live-grid-kdb-port.md)."""
    import boto3
    from botocore.exceptions import ClientError

    _load("s3_init").main(attempts=1, delay=0)
    c = boto3.client("s3", endpoint_url=f"http://{store_env['DELTA_S3_ENDPOINT']}:{store_env['DELTA_S3_PORT']}",
                     aws_access_key_id="EXAMPLE_ACCESS", aws_secret_access_key="EXAMPLE_SECRET", region_name="us-east-1")
    key = "ticks_live/AAPL_2026_10_09/_delta_log/00000000000000000000.json"
    c.put_object(Bucket=store_env["DELTA_S3_BUCKET"], Key=key, Body=b"{}", IfNoneMatch="*")
    with pytest.raises(ClientError) as err:
        c.put_object(Bucket=store_env["DELTA_S3_BUCKET"], Key=key, Body=b"{}", IfNoneMatch="*")
    assert err.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
