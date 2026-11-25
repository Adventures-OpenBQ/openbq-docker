# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbq-docker v10: the chart seam reads flushed days back from the Delta store.

The tables are written exactly as scripts/eod_dump.py writes them (one Delta
table per (symbol, UTC day), `<library>/<SYM>_<YYYY_MM_DD>`, columns date,
price, size), with synthetic ticks, to a local directory and to a moto S3
server. kdb is the tick-plant simulation (v10/kdb/source/q/tests/tickplant_sim.py).
No network beyond 127.0.0.1, no EODHD.
"""
from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from deltalake import write_deltalake

from app import lake as lake_mod
from app import main as main_mod
from app.lake import LakeTicks, bars, day_aligned, resolve, table_key
from app.main import build_series

_SIM = Path(__file__).resolve().parents[2] / "v10" / "kdb" / "source" / "q" / "tests" / "tickplant_sim.py"
_spec = importlib.util.spec_from_file_location("tickplant_sim", _SIM)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)

TODAY = date(2026, 10, 12)
D1, D2, D3 = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11)


def _ticks(day: date, start_hm=(14, 30), minutes=3, per_minute=4, base=100.0):
    t0 = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_hm[0], minutes=start_hm[1])
    rows = [(t0 + timedelta(seconds=15 * i), base + i, 1.0 + (i % 2))
            for i in range(minutes * per_minute)]
    return pd.DataFrame(rows, columns=["date", "price", "size"])


def _flush(base: str, day: date, frame: pd.DataFrame, sym="AAPL", options=None):
    """What eod_dump.dump_day writes for one (symbol, day)."""
    write_deltalake(f"{base}/ticks_live/{table_key(sym, day)}", frame, mode="overwrite",
                    schema_mode="overwrite", storage_options=options or None)


def _history(days):
    """Provider 1m history: one bar per minute 14:00-15:00 on each day."""
    rows = []
    for day in days:
        t0 = datetime.combine(day, datetime.min.time()) + timedelta(hours=14)
        rows += [{"date": (t0 + timedelta(minutes=m)).isoformat(), "open": 1.0, "high": 1.0,
                  "low": 1.0, "close": 1.0, "volume": 1.0} for m in range(60)]
    return rows


@pytest.fixture
def history(monkeypatch):
    async def fake_fetch(symbol, interval, start, end, provider):
        return _history([D1, D2, D3, TODAY]), {"cache": "upstream"}
    monkeypatch.setattr(main_mod, "fetch_series", fake_fetch)


# -- configuration -----------------------------------------------------------------

def test_the_s3_contract_is_path_style_conditional_put_and_plain_http_on_the_bridge():
    env = {"DELTA_S3_ENDPOINT": "rustfs", "DELTA_S3_PORT": "9000", "DELTA_S3_SECURE": "false",
           "DELTA_S3_BUCKET": "openbq", "DELTA_S3_ACCESS": "EXAMPLE_ACCESS", "DELTA_S3_SECRET": "EXAMPLE_SECRET"}
    base, opts = resolve(env)
    assert base == "s3://openbq"
    assert opts["aws_endpoint"] == "http://rustfs:9000"
    assert opts["aws_virtual_hosted_style_request"] == "false"
    assert opts["aws_conditional_put"] == "etag"
    assert opts["aws_allow_http"] == "true"


def test_the_read_back_is_off_without_the_switch_or_without_a_store(tmp_path):
    assert LakeTicks.from_env({"DELTA_URI": str(tmp_path)}) is None
    assert LakeTicks.from_env({"LIVE_GRID_LAKE_READBACK": "true"}) is None
    # a partial S3 configuration never falls back to a container directory
    assert LakeTicks.from_env({"LIVE_GRID_LAKE_READBACK": "true", "DELTA_S3_ENDPOINT": "rustfs"}) is None
    reader = LakeTicks.from_env({"LIVE_GRID_LAKE_READBACK": "true", "DELTA_URI": str(tmp_path),
                                 "LIVE_GRID_LAKE_LIBRARY": "ticks_live", "LIVE_GRID_LAKE_MAX_DAYS": "3"})
    assert reader.base == str(tmp_path) and reader.max_days == 3


def test_the_app_builds_no_reader_unless_asked(monkeypatch):
    monkeypatch.delenv("LIVE_GRID_LAKE_READBACK", raising=False)
    assert LakeTicks.from_env() is None


def test_only_intraday_intervals_that_tile_a_day_use_the_store():
    assert day_aligned("1m") and day_aligned("5m") and day_aligned("1h") and day_aligned("90m")
    assert not day_aligned("7m") and not day_aligned("1d") and not day_aligned("1w")


def test_the_key_is_eod_dumps():
    assert table_key("BTC-USD", D1) == "BTC_USD_2026_10_09"


def test_bars_match_the_kdb_aggregation():
    ticks = _ticks(D1).rename(columns={"date": "time"})
    ticks["sym"] = "AAPL"
    want = sim.aggregate(ticks, 60 * 10**9)
    got = bars(ticks, "1m")
    assert [r["open"] for r in got] == list(want["open"])
    assert [r["close"] for r in got] == list(want["close"])
    assert [r["vwap"] for r in got] == pytest.approx(list(want["vwap"]))
    assert [r["date"] for r in got] == [t.to_pydatetime() for t in want["t"]]


# -- the join ------------------------------------------------------------------------

async def test_flushed_days_replace_history_only_where_ticks_cover(tmp_path, history):
    _flush(str(tmp_path), D2, _ticks(D2))  # 14:30-14:33
    reader = LakeTicks(str(tmp_path), {}, max_days=10)
    out, meta = await lake_mod.series_with_lake(
        "AAPL", "1m", D1.isoformat(), TODAY.isoformat(), None, timedelta(days=1),
        _history([D1, D2, D3, TODAY]), {"rows_from_ticks": 0, "seam": None}, reader, today=TODAY)
    assert meta["lake_days"] == ["2026-10-10"] and meta["rows_from_lake"] == 3
    on_d2 = [r for r in out if str(r["date"]).startswith("2026-10-10")]
    # 60 history minutes on D2, three of them replaced by tick-true bars
    assert len(on_d2) == 60
    replaced = [r for r in on_d2 if isinstance(r["date"], datetime)]
    assert [r["date"].strftime("%H:%M") for r in replaced] == ["14:30", "14:31", "14:32"]
    assert replaced[0]["open"] == 100.0 and replaced[0]["vwap"] is not None
    # the rest of the morning and afternoon is still history
    assert len([r for r in out if str(r["date"]).startswith("2026-10-09")]) == 60


async def test_kdb_owns_only_what_follows_the_last_flushed_day(tmp_path, history, monkeypatch):
    _flush(str(tmp_path), D3, _ticks(D3, start_hm=(23, 58), minutes=2))
    host = sim.Host(tmp_path / "kdb", today=lambda: TODAY)
    plant = host.start()
    # kdb's rolling window still holds the end of D3 AND today
    frame = pd.concat([_ticks(D3, start_hm=(23, 58), minutes=2), _ticks(TODAY, start_hm=(14, 0))])
    plant.upd("trades", frame.rename(columns={"date": "time"}).assign(sym="AAPL")[["time", "sym", "price", "size"]])

    from openbq_kdb import session as session_mod
    from openbq_kdb.session import KdbSession
    from openbq_kdb.store import KdbStore

    from app.recorder import TickRecorder

    monkeypatch.setattr(KdbSession, "_connect", lambda self, host_=None, **k: host.connect())
    monkeypatch.setattr(session_mod, "_RETRY_AFTER_S", 0.0)
    for k, v in {"KDB_EMBEDDED": "false", "KDB_BIND_HOST": "kdb", "KDB_PORT": "5000"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KDB_HOST", raising=False)
    from openbq_kdb.config import resolve_config

    recorder = TickRecorder(KdbStore(KdbSession(resolve_config())), window=timedelta(days=2))
    reader = LakeTicks(str(tmp_path), {}, max_days=10)
    out, meta = await lake_mod.series_with_lake(
        "AAPL", "1m", D3.isoformat(), TODAY.isoformat(), recorder, recorder.window,
        _history([D3, TODAY]), {"rows_from_ticks": 0, "seam": None}, reader, today=TODAY)
    assert meta["lake_days"] == ["2026-10-11"]
    assert meta["seam"] == "2026-10-12T00:00:00"  # not kdb's first tick on D3
    assert meta["rows_from_ticks"] == 3 and meta["rows_from_lake"] == 2
    dates = [str(r["date"]) for r in out]
    assert len(dates) == len(set(dates))  # no bar twice
    recorder.store.session.close()


async def test_a_store_outage_degrades_to_kdb_and_history(tmp_path, history):
    class Broken(LakeTicks):
        def read_day(self, symbol, day):
            raise OSError("connection refused")

    out, meta = await lake_mod.series_with_lake(
        "AAPL", "1m", D1.isoformat(), TODAY.isoformat(), None, timedelta(days=1),
        _history([D1]), {"rows_from_ticks": 0, "seam": None}, Broken(str(tmp_path), {}), today=TODAY)
    assert meta["rows_from_lake"] == 0 and len(out) == 60


async def test_build_series_without_a_reader_is_the_donor_path(history):
    out, meta = await build_series("AAPL", "1m", D1.isoformat(), TODAY.isoformat(), None,
                                   timedelta(days=1))
    assert "rows_from_lake" not in meta and len(out) == 240


async def test_build_series_with_a_reader_and_a_daily_interval_is_the_donor_path(tmp_path, history):
    _flush(str(tmp_path), D2, _ticks(D2))
    out, meta = await build_series("AAPL", "1d", D1.isoformat(), TODAY.isoformat(), None,
                                   timedelta(days=1), lake=LakeTicks(str(tmp_path), {}))
    assert "rows_from_lake" not in meta


def test_wanted_days_are_past_whole_days_capped_at_max_days(tmp_path):
    reader = LakeTicks(str(tmp_path), {}, max_days=2)
    assert reader.wanted_days("2026-10-01", "2026-10-12", TODAY) == [D2, D3]
    assert reader.wanted_days("2026-10-11", "2026-10-11", TODAY) == [D3]
    assert reader.wanted_days("2026-10-12", "2026-10-12", TODAY) == []


# -- over S3 (moto) ------------------------------------------------------------------

def test_read_back_over_s3_with_the_rustfs_contract(monkeypatch):
    from moto.server import ThreadedMotoServer
    from pyarrow import fs as pafs

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    try:
        host, port = server.get_host_and_port()
        env = {"LIVE_GRID_LAKE_READBACK": "true", "DELTA_S3_ENDPOINT": host,
               "DELTA_S3_PORT": str(port), "DELTA_S3_SECURE": "false", "DELTA_S3_BUCKET": "openbq",
               "DELTA_S3_ACCESS": "EXAMPLE_ACCESS", "DELTA_S3_SECRET": "EXAMPLE_SECRET"}
        pafs.S3FileSystem(access_key="EXAMPLE_ACCESS", secret_key="EXAMPLE_SECRET", scheme="http",
                          endpoint_override=f"http://{host}:{port}", force_virtual_addressing=False,
                          allow_bucket_creation=True).create_dir("openbq")
        reader = LakeTicks.from_env(env)
        _flush(reader.base, D2, _ticks(D2), options=reader.storage_options)
        got = reader.read_day("AAPL", D2)
        assert len(got) == 12 and list(got.columns) == ["time", "price", "size"]
        assert reader.read_day("AAPL", D1) is None
    finally:
        server.stop()
