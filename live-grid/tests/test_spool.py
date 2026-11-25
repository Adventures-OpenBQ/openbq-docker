# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The tick spool (openbq-docker v10, user ruling 2026-10-12).

Ticks must be spooled to the filesystem and recovered when a service restarts.
The Mac drill that prompted it: kdb SIGKILLed and restarted, live-grid's
/health afterwards `{'buffered': 0, 'written': 2436, 'dropped': 2459}` -- about
100 s of BTC-USD/ETH-USD ticks lost to a 60 s retry latch and a recorder that
dropped every failed batch.

The kdb service is v10/kdb/source/q/tests/tickplant_sim.py (startup.q + persist.q, its
tick log and boot replay), as in test_crash_recovery.py. The real KdbSession,
KdbStore, TickRecorder and TickSpool run unmodified; only `KdbSession._connect`
dials the simulated host, and the session's clock is injected so the backoff
is driven without sleeping.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import spool as spool_mod
from app.main import create_app
from app.recorder import TickRecorder
from app.spool import TickSpool, decode, encode
from openbq_kdb.config import resolve_config
from openbq_kdb.session import KdbSession
from openbq_kdb.store import KdbStore
from tests.test_main import FakeRest, _NullWs
from tests.test_openbq_v10 import api  # noqa: F401 - the recorded openbq-api fixture

_SIM = Path(__file__).resolve().parents[2] / "v10" / "kdb" / "source" / "q" / "tests" / "tickplant_sim.py"
_spec = importlib.util.spec_from_file_location("tickplant_sim", _SIM)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)

T0 = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=1)


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


@pytest.fixture
def host(tmp_path, monkeypatch):
    h = sim.Host(tmp_path / "kdb-data", today=date.today)
    monkeypatch.setattr(KdbSession, "_connect", lambda self, host=None: h.connect())
    for name in ("KDB_HOST", "QHOME", "KDB_LOCAL_QHOME", "KDB_RETRY_INITIAL_S", "KDB_RETRY_MAX_S"):
        monkeypatch.delenv(name, raising=False)
    # live-grid's environment in docker-compose.yml
    monkeypatch.setenv("LIVE_GRID_CHART", "true")
    monkeypatch.setenv("KDB_EMBEDDED", "false")
    monkeypatch.setenv("KDB_BIND_HOST", "kdb")
    monkeypatch.setenv("KDB_PORT", "5000")
    monkeypatch.setenv("OPENBB_HISTORY_NAMESPACE", "eodhd")
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "live-grid-data" / "watchlist.json"))
    monkeypatch.setenv("LIVE_GRID_SPOOL_DIR", str(tmp_path / "live-grid-data" / "spool"))
    return h


def _spool_dir(tmp_path) -> Path:
    return tmp_path / "live-grid-data" / "spool"


def _recorder(tmp_path, clock, **spool_kw):
    session = KdbSession(resolve_config(), clock=clock)
    spool = TickSpool(_spool_dir(tmp_path), clock=clock, **spool_kw)
    return TickRecorder(KdbStore(session), window=timedelta(days=1), spool=spool, clock=clock)


class Feed:
    """BTC-USD/ETH-USD ticks with distinct, increasing stamps; remembers what it sent."""

    def __init__(self):
        self.sent: list[tuple] = []
        self.i = 0

    def tick(self, recorder, n):
        for _ in range(n):
            sym = "BTC-USD" if self.i % 2 == 0 else "ETH-USD"
            stamp = T0 + timedelta(milliseconds=40 * self.i)
            price = 60000.0 + self.i * 0.25 if sym == "BTC-USD" else 2500.0 + self.i * 0.01
            recorder.record(sym, price, 0.001 * (1 + self.i % 5), stamp)
            self.sent.append((stamp, sym, price, 0.001 * (1 + self.i % 5)))
            self.i += 1


def _held(host) -> list[tuple]:
    t = host.plant.trades
    return [(r.time.to_pydatetime(), r.sym, float(r.price), float(r.size)) for r in t.itertuples()]


def _assert_exactly_once_in_order(host, feed):
    held = _held(host)
    assert len(held) == len(set(held)), "a tick landed twice"
    assert held == feed.sent, "kdb does not hold every tick exactly once, in feed order"


def _tick_files(tmp_path):
    d = _spool_dir(tmp_path)
    return sorted(p.name for p in d.glob("ticks_*.jsonl")) if d.exists() else []


# -- the Mac drill, modelled ---------------------------------------------------------


def test_a_kdb_outage_mid_stream_spools_and_every_tick_lands_once_in_order(host, tmp_path):
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    for _ in range(5):  # 0.2 s flushes at ~24 ticks/s
        feed.tick(rec, 5)
        rec.flush()
    assert rec.written == 25

    host.kill()  # docker compose kill -s SIGKILL kdb
    for _ in range(50):  # ten seconds of outage, flushing every 0.2 s
        feed.tick(rec, 5)
        rec.flush()
        clock.now += 0.2
    assert rec.dropped == 0
    assert rec.spooled == 250
    assert rec.stats()["spooled"] == 250
    assert _tick_files(tmp_path)

    host.start()  # docker compose start kdb: persist.q replays its own log
    assert len(host.plant.trades) == 25
    clock.now += 15.0  # past any backoff window
    feed.tick(rec, 5)  # live ticks arriving as kdb comes back go BEHIND the backlog
    rec.flush()
    assert rec.spooled == 0
    assert rec.replayed == 255
    assert rec.written == 280
    assert rec.dropped == 0
    for _ in range(3):  # and with the spool empty, straight to kdb again
        feed.tick(rec, 5)
        rec.flush()
    assert rec.replayed == 255 and rec.written == 295
    _assert_exactly_once_in_order(host, feed)
    assert _tick_files(tmp_path) == []

    # kdb's own log has everything too: a second kdb restart replays all of it
    host.kill()
    host.start()
    _assert_exactly_once_in_order(host, feed)
    rec.store.session.close()


def test_reconnect_happens_on_the_backoff_not_a_sixty_second_latch(host, tmp_path):
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(rec, 4)
    rec.flush()
    host.kill()
    feed.tick(rec, 4)
    rec.flush()  # the dead connection fails, one reconnect is refused: 1 s backoff
    host.start()
    feed.tick(rec, 4)
    rec.flush()
    assert rec.spooled == 8 and rec.replayed == 0  # inside the 1 s window
    clock.now += 1.0
    rec.flush()
    assert rec.spooled == 0 and rec.replayed == 8
    _assert_exactly_once_in_order(host, feed)
    rec.store.session.close()


def test_no_replay_is_staged_while_the_session_is_backing_off(host, tmp_path, monkeypatch):
    clock = Clock()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(rec, 3)
    rec.flush()  # no kdb at all: refused, 1 s backoff, ticks spooled
    staged = []
    monkeypatch.setattr(rec.spool, "stage", lambda seg: staged.append(seg))
    for _ in range(4):
        feed.tick(rec, 1)
        rec.flush()
    assert staged == [], "the cursor must not be fsynced on every flush during an outage"
    assert rec.spooled == 7
    rec.store.session.close()


# -- in-doubt writes: never twice --------------------------------------------------------


def test_a_live_write_that_kdb_applied_before_dying_is_not_sent_again(host, tmp_path):
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(rec, 10)
    rec.flush()
    host.plant.die_after_next_upd = True  # logged and applied, reply lost
    feed.tick(rec, 7)
    assert rec.flush() == 0
    assert rec.spooled == 7  # in doubt, kept
    lines = (_spool_dir(tmp_path) / _tick_files(tmp_path)[0]).read_text().splitlines()
    assert all(len(json.loads(x)) == 5 for x in lines), "in-doubt lines carry their batch id"

    host.start()  # persist.q's replay brings the applied batch back
    assert len(host.plant.trades) == 17
    clock.now += 15.0
    feed.tick(rec, 3)
    rec.flush()
    assert rec.deduped == 7 and rec.replayed == 3 and rec.spooled == 0
    _assert_exactly_once_in_order(host, feed)
    rec.store.session.close()


def test_an_in_doubt_batch_that_never_landed_is_sent(host, tmp_path, monkeypatch):
    """The other half: the write raised and kdb did NOT apply it."""
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    real = rec.store.write_ticks
    calls = {"n": 0}

    def flaky(frame):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Attempted to use a closed IPC connection")
        return real(frame)

    monkeypatch.setattr(rec.store, "write_ticks", flaky)
    feed.tick(rec, 4)
    rec.flush()
    feed.tick(rec, 4)
    rec.flush()  # raised: in doubt
    assert rec.spooled == 4
    feed.tick(rec, 4)
    rec.flush()  # probe says absent: sent, then the rest
    assert rec.deduped == 0 and rec.replayed == 8 and rec.spooled == 0
    _assert_exactly_once_in_order(host, feed)
    rec.store.session.close()


def test_a_replay_write_that_kdb_applied_before_dying_is_not_sent_again(host, tmp_path):
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(rec, 5)
    rec.flush()
    host.kill()
    feed.tick(rec, 20)
    rec.flush()
    host.start()
    host.plant.die_after_next_upd = True  # the replay itself is applied, then q dies
    clock.now += 15.0
    rec.flush()
    assert rec.spooled == 20 and rec.replayed == 0
    host.start()
    clock.now += 15.0
    rec.flush()
    assert rec.deduped == 20 and rec.spooled == 0
    _assert_exactly_once_in_order(host, feed)
    rec.store.session.close()


# -- live-grid itself restarts ---------------------------------------------------------


def test_a_restarted_live_grid_replays_a_non_empty_spool(host, tmp_path):
    clock = Clock()
    host.start()
    first = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(first, 6)
    first.flush()
    host.kill()
    for _ in range(10):
        feed.tick(first, 4)
        first.flush()
    assert first.spooled == 40
    # live-grid is SIGKILLed: no stash, no close, the open file handle just dies
    del first

    host.start()
    second = _recorder(tmp_path, Clock())
    assert second.spooled == 40, "leftovers are counted at startup"
    second.flush()  # the first flush replays them, before any new tick
    assert second.spooled == 0 and second.replayed == 40 and second.dropped == 0
    feed.tick(second, 5)
    second.flush()
    _assert_exactly_once_in_order(host, feed)
    second.store.session.close()


def test_live_grid_killed_mid_replay_does_not_duplicate_the_staged_segment(host, tmp_path, monkeypatch):
    """SIGKILL between kdb applying a replayed segment and the spool acknowledging it."""
    clock = Clock()
    host.start()
    first = _recorder(tmp_path, clock)
    feed = Feed()
    first.flush()
    host.kill()
    feed.tick(first, 12)
    first.flush()
    host.start()
    clock.now += 15.0

    class Killed(BaseException):
        pass

    def die(seg):
        raise Killed()  # the process is gone after kdb confirmed, before the ack

    monkeypatch.setattr(first.spool, "ack", die)
    with pytest.raises(Killed):
        first.flush()
    assert len(host.plant.trades) == 12  # kdb has them
    state = json.loads((_spool_dir(tmp_path) / spool_mod.STATE_NAME).read_text())
    assert state["inflight"] is not None, "the segment was staged before it was sent"

    second = _recorder(tmp_path, Clock())
    assert second.spooled == 12
    second.flush()
    assert second.deduped == 12 and second.replayed == 0 and second.spooled == 0
    _assert_exactly_once_in_order(host, feed)
    second.store.session.close()


def test_through_the_app_health_reports_spooled_then_replayed(host, tmp_path, api):
    clock = Clock()
    host.kill()  # kdb is down while ticks arrive
    first = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(first, 30)
    first.flush()
    assert first.spooled == 30
    first.store.session.close()

    host.start()
    app = create_app(api_key="test-key", seed_client=FakeRest(),
                     client_factory=lambda *a, **k: _NullWs())
    with TestClient(app) as client:
        deadline = time.monotonic() + 10.0
        ticks = client.get("/health").json()["ticks"]
        while ticks["replayed"] < 30 and time.monotonic() < deadline:
            time.sleep(0.05)
            ticks = client.get("/health").json()["ticks"]
        assert ticks["replayed"] == 30
        assert ticks["spooled"] == 0
        assert ticks["dropped"] == 0
        assert ticks["written"] == 30
        # The restored connection retains the configured Compose host and port.
        assert ticks["endpoint"] == "kdb:5000"
        assert len(client.get("/ticks?symbol=BTC-USD&limit=1000").json()["ticks"]) == 15
    _assert_exactly_once_in_order(host, feed)


def test_a_graceful_stop_stashes_the_unflushed_buffer(host, tmp_path):
    clock = Clock()
    host.start()
    rec = _recorder(tmp_path, clock)
    feed = Feed()
    feed.tick(rec, 9)  # recorded, never flushed
    assert rec.stash() == 9
    assert rec.buffered == 0
    again = _recorder(tmp_path, Clock())
    assert again.spooled == 9
    again.flush()
    _assert_exactly_once_in_order(host, feed)
    again.store.session.close()


# -- bounded ------------------------------------------------------------------------


def test_the_cap_is_honoured_and_counted_as_dropped(host, tmp_path):
    line = len(encode((T0, "BTC-USD", 60000.0, 0.001)))
    clock = Clock()
    rec = _recorder(tmp_path, clock, max_bytes=line * 30)  # room for ~30 ticks
    feed = Feed()
    for _ in range(10):
        feed.tick(rec, 10)
        rec.flush()
    spooled = rec.spooled
    assert 0 < spooled <= 30
    assert rec.dropped == 100 - spooled
    assert rec.stats()["dropped"] == 100 - spooled
    on_disk = sum(p.stat().st_size for p in _spool_dir(tmp_path).glob("ticks_*.jsonl"))
    assert on_disk <= line * 30
    # what was kept is the OLDEST, in order: the newest are the ones refused
    host.start()
    clock.now += 15.0
    rec.flush()
    assert _held(host) == feed.sent[:spooled]
    rec.store.session.close()


def test_the_cap_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_GRID_SPOOL_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("LIVE_GRID_SPOOL_MAX_MB", "3")
    monkeypatch.setenv("LIVE_GRID_SPOOL_FSYNC_S", "0.5")
    s = spool_mod.from_env("/data/watchlist.json")
    assert s.dir == tmp_path / "s" and s.max_bytes == 3 * 2**20 and s.fsync_interval == 0.5


def test_the_default_spool_sits_beside_the_watchlist_on_the_volume(monkeypatch, tmp_path):
    monkeypatch.delenv("LIVE_GRID_SPOOL_DIR", raising=False)
    monkeypatch.delenv("LIVE_GRID_SPOOL_MAX_MB", raising=False)
    monkeypatch.delenv("LIVE_GRID_SPOOL_FSYNC_S", raising=False)
    assert spool_mod.from_env("/data/watchlist.json").dir == Path("/data/spool")
    s = spool_mod.from_env(str(tmp_path / "vol" / "watchlist.json"))
    assert s.dir == tmp_path / "vol" / "spool"
    assert s.max_bytes == 256 * 2**20 and s.fsync_interval == 1.0
    assert not s.dir.exists(), "the directory is made on the first append, not at startup"
    s.append([(T0, "BTC-USD", 1.0, 0.0)])
    assert s.count == 1 and len(list(s.dir.glob("ticks_*.jsonl"))) == 1


# -- the file format and durability ------------------------------------------------------


def test_lines_round_trip_exactly_including_utc_stamps():
    stamp = datetime(2026, 10, 12, 14, 0, 0, 123456, tzinfo=timezone.utc)
    row = (stamp, "BTC-USD", 62000.123456789, 0.00012)
    got, batch = decode(encode(row))
    assert got == row and batch is None
    got, batch = decode(encode(row, "b1"))
    assert got == row and batch == "b1"


def test_fsync_runs_at_the_configured_cadence(tmp_path, monkeypatch):
    clock = Clock()
    synced = []
    real = os.fsync
    monkeypatch.setattr(spool_mod.os, "fsync", lambda fd: (synced.append(clock.now), real(fd)))
    s = TickSpool(tmp_path / "spool", fsync_interval=1.0, clock=clock)
    synced.clear()
    row = (T0, "BTC-USD", 1.0, 0.0)
    for _ in range(50):  # 10 s of 0.2 s flushes
        s.append([row])
        clock.now += 0.2
    file_syncs = [t for t in synced]
    # the cursor save as the file opens (D16: its seq; the temp file and the directory), one
    # directory fsync for the new file, then at most one data fsync per second
    assert 11 <= len(file_syncs) <= 14
    gaps = [b - a for a, b in zip(file_syncs[3:], file_syncs[4:])]
    assert all(g >= 1.0 - 1e-9 for g in gaps)
    # an idle spool with unsynced appends is synced by the next flush's sync()
    s.append([row])
    clock.now += 1.0
    assert s.sync() is True
    assert s.sync() is False  # nothing new


def test_a_torn_final_line_is_cut_at_startup(tmp_path):
    d = tmp_path / "spool"
    d.mkdir()
    good = encode((T0, "BTC-USD", 1.0, 0.0)) + encode((T0, "ETH-USD", 2.0, 0.0))
    (d / "ticks_2026-10-12.jsonl").write_bytes(good + b'["2026-10-12T14:0')
    s = TickSpool(d)
    assert s.count == 2 and s.dropped == 1
    assert (d / "ticks_2026-10-12.jsonl").read_bytes() == good
    s.append([(T0, "BTC-USD", 3.0, 0.0)])  # a new process appends to a new file
    seg = s.head(100)
    assert [r[2] for r in seg.rows] == [1.0, 2.0]
    s.ack(seg)
    assert [r[2] for r in s.head(100).rows] == [3.0]
    s.close()


def test_files_replay_oldest_first_and_are_deleted_only_when_acknowledged(tmp_path):
    days = iter([datetime(2026, 10, 11, 23, 59, tzinfo=timezone.utc),
                 datetime(2026, 10, 12, 0, 1, tzinfo=timezone.utc)])
    current = {"d": next(days)}
    s = TickSpool(tmp_path / "spool", utcnow=lambda: current["d"])
    s.append([(T0, "BTC-USD", 1.0, 0.0)])
    current["d"] = next(days)
    s.append([(T0, "BTC-USD", 2.0, 0.0)])
    assert sorted(p.name for p in (tmp_path / "spool").glob("ticks_*")) == [
        "ticks_2026-10-11_000000.jsonl", "ticks_2026-10-12_000000.jsonl"]
    seg = s.head(100)
    assert seg.file == "ticks_2026-10-11_000000.jsonl" and [r[2] for r in seg.rows] == [1.0]
    assert (tmp_path / "spool" / seg.file).exists()  # not before the ack
    s.ack(seg)
    assert not (tmp_path / "spool" / "ticks_2026-10-11_000000.jsonl").exists()
    seg = s.head(100)
    assert [r[2] for r in seg.rows] == [2.0]
    s.ack(seg)
    assert s.count == 0 and s.bytes == 0
    assert list((tmp_path / "spool").glob("ticks_*")) == []


def test_files_roll_by_size_so_replay_frees_disk_while_the_backlog_drains(tmp_path):
    line = len(encode((T0, "BTC-USD", 60000.0, 0.001)))
    s = TickSpool(tmp_path / "spool", max_bytes=8 * 64 * 2**10)  # roll at 64 KB
    per_file = (64 * 2**10) // line
    rows = [(T0 + timedelta(milliseconds=i), "BTC-USD", 60000.0, 0.001) for i in range(per_file * 3)]
    for i in range(0, len(rows), 50):
        s.append(rows[i:i + 50])
    names = sorted(p.name for p in s.dir.glob("ticks_*"))
    assert len(names) >= 3 and names == sorted(names)
    assert all(p.stat().st_size <= 64 * 2**10 for p in s.dir.glob("ticks_*"))
    before = s.bytes
    replayed = []
    while (seg := s.head(per_file)) is not None and len(list(s.dir.glob("ticks_*"))) == len(names):
        replayed += seg.rows
        s.ack(seg)
    assert s.bytes < before, "a fully acknowledged file is deleted before the backlog is empty"
    while (seg := s.head(per_file)) is not None:
        replayed += seg.rows
        s.ack(seg)
    assert replayed == rows and s.bytes == 0


def test_an_in_doubt_batch_is_one_segment_never_merged_with_plain_lines(tmp_path):
    s = TickSpool(tmp_path / "spool")
    rows = [(T0 + timedelta(seconds=i), "BTC-USD", float(i), 0.0) for i in range(9)]
    s.append(rows[:3])
    s.append(rows[3:6], doubt=True)
    s.append(rows[6:])
    sizes = []
    while (seg := s.head(100)) is not None:
        sizes.append((len(seg.rows), seg.doubt))
        s.ack(seg)
    assert sizes == [(3, False), (3, True), (3, False)]


# -- the flush race the spool work exposed -----------------------------------------------


def test_a_tick_recorded_while_a_flush_is_writing_is_not_lost():
    """record() runs on the event loop while flush() writes on a worker thread.
    The donor copied the buffer, wrote it, then cleared it -- discarding any tick
    appended in between. Modelled by a store that records during its write."""

    class Store:
        def __init__(self):
            self.rec = None
            self.frames = []

        def write_ticks(self, frame):
            if not self.frames:
                self.rec.record("BTC-USD", 2.0, 0.0, T0 + timedelta(seconds=1))
            self.frames.append(frame)
            return len(frame)

    store = Store()
    rec = TickRecorder(store)
    store.rec = rec
    rec.record("BTC-USD", 1.0, 0.0, T0)
    assert rec.flush() == 1
    assert rec.buffered == 1, "the tick recorded during the write was discarded"
    assert rec.flush() == 1
    assert [list(f["price"]) for f in store.frames] == [[1.0], [2.0]]
    assert rec.dropped == 0


def test_spooled_frames_match_live_frames(tmp_path):
    """A replayed batch must reach write_ticks shaped exactly like a live one."""
    stamp = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)
    rows = [(stamp, "BTC-USD", 1.5, 0.0), (stamp, "ETH-USD", 2.5, 0.25)]
    s = TickSpool(tmp_path / "spool")
    s.append(rows)
    seg = s.head(100)
    live = TickRecorder._frame_of(rows)
    replay = TickRecorder._frame_of(seg.rows)
    pd.testing.assert_frame_equal(live, replay)


def test_a_failed_append_is_counted_dropped_and_leaves_no_partial_line(tmp_path, monkeypatch):
    """ENOSPC half way through a write: the ticks are dropped and counted, never
    left as a torn line that the next append would run into."""
    s = TickSpool(tmp_path / "spool")
    s.append([(T0, "BTC-USD", 1.0, 0.0)])
    real_handle = s._handle

    class HalfFull:
        def __init__(self, fh):
            self.fh = fh

        def write(self, data):
            self.fh.write(data[: len(data) // 2])
            self.fh.flush()
            raise OSError(28, "No space left on device")

        def __getattr__(self, name):
            return getattr(self.fh, name)

    monkeypatch.setattr(s, "_handle", lambda incoming: HalfFull(real_handle(incoming)))
    assert s.append([(T0, "ETH-USD", 2.0, 0.0), (T0, "ETH-USD", 3.0, 0.0)]) == 0
    assert s.dropped == 2 and s.count == 1
    monkeypatch.setattr(s, "_handle", real_handle)
    s.append([(T0, "BTC-USD", 4.0, 0.0)])
    got = []
    while (seg := s.head(100)) is not None:
        got += [r[2] for r in seg.rows]
        s.ack(seg)
    assert got == [1.0, 4.0]


# -- review fixes 2026-10-16 (D5, D15, D16) ------------------------------------------


class _Poison:
    """A store that refuses any batch holding a price of -1 with the same q error, every time."""

    def __init__(self):
        self.frames = []

    def write_ticks(self, frame):
        if (frame["price"] == -1).any():
            raise RuntimeError("'type")
        self.frames.append(frame)
        return len(frame)

    def ticks_present(self, frame):
        return 0


class _Wall:
    """An injectable UTC clock for the spool's backoff and quarantine floor."""

    def __init__(self):
        self.t = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += timedelta(seconds=seconds)

    def mono(self):
        return self.t.timestamp()


def _poison_run(tmp_path, wall, seconds, store=None, rec=None, poison=True):
    """Record one poison tick (unless poison=False), then a good tick and a flush every
    simulated second. Good prices keep rising across calls."""
    store = store or _Poison()
    rec = rec or TickRecorder(store, spool=TickSpool(tmp_path / "spool", utcnow=wall, clock=wall.mono))
    if poison:
        rec.record("BTC-USD", -1, 0.0, T0)
        rec.flush()  # sent, raised: spooled in doubt
    base = getattr(rec, "_test_ticks", 0)
    rec._test_ticks = base + seconds
    for i in range(base + 1, base + seconds + 1):
        wall.tick(1)
        rec.record("BTC-USD", float(i), 0.0, T0 + timedelta(seconds=i))
        rec.flush()
    return store, rec


def test_a_batch_that_always_fails_is_quarantined_only_after_backoff_and_a_minute(tmp_path, caplog):
    """D5, then Q3 (re-review 2026-10-16): an error that recurs on every resend used to block the
    spool for good; then 5 sends in ~1 s quarantined it, so a q error lasting a second (a full
    kdb-data disk) lost the batch for good. Now resends back off exponentially and the segment
    is quarantined only after MAX_FAILURES sends AND QUARANTINE_MIN_S of wall clock."""
    wall = _Wall()
    attempts = []

    class Counting(_Poison):
        def write_ticks(self, frame):
            if (frame["price"] == -1).any():
                attempts.append(wall.t)
            return super().write_ticks(frame)

    store, rec = _poison_run(tmp_path, wall, spool_mod.QUARANTINE_MIN_S - 1, store=Counting())
    assert rec.stats()["quarantined"] == 0 and rec.spooled > 0, "quarantined before the floor"
    # backed off: far fewer sends than flushes, with growing gaps
    gaps = [(b - a).total_seconds() for a, b in zip(attempts[1:], attempts[2:])]
    assert gaps == sorted(gaps) and gaps[-1] >= 16
    _poison_run(tmp_path, wall, 200, store=store, rec=rec, poison=False)
    assert rec.stats()["quarantined"] == 1 and rec.spooled == 0
    assert len(attempts) == 1 + spool_mod.MAX_FAILURES
    written = [p for f in store.frames for p in f["price"]]
    assert written == sorted(written) and -1.0 not in written and len(written) > 200
    (qfile,) = (tmp_path / "spool" / spool_mod.QUARANTINE).iterdir()
    assert [decode(line)[0][2] for line in qfile.read_bytes().splitlines(keepends=True)] == [-1.0]
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and r.name == "app.recorder"]
    assert len(warnings) <= 3, [r.getMessage() for r in warnings]
    assert TickSpool(tmp_path / "spool").quarantined == 1  # a restart still reports it


def test_an_error_that_clears_within_the_backoff_loses_nothing(tmp_path):
    """Q3: the full-disk case. The q error lasts ~30 s, then q accepts again: the batch lands,
    in order before every newer tick, and nothing is quarantined."""
    wall = _Wall()
    healed = {"at": wall.t + timedelta(seconds=30)}

    class Healing(_Poison):
        def write_ticks(self, frame):
            if wall.t >= healed["at"]:
                self.frames.append(frame)
                return len(frame)
            return super().write_ticks(frame)

    store, rec = _poison_run(tmp_path, wall, 120, store=Healing())
    written = [p for f in store.frames for p in f["price"]]
    assert written[0] == -1.0 and written[1:] == sorted(written[1:]) and len(written) == 121
    assert rec.stats()["quarantined"] == 0 and rec.spooled == 0


def test_the_failure_count_and_its_start_survive_a_restart(tmp_path):
    """D5/Q3: a restart resets neither the count nor the wall-clock start, so a poison segment
    cannot block forever, and a restart cannot make it quarantine early either."""
    wall = _Wall()
    _, rec = _poison_run(tmp_path, wall, 10)
    fails = rec.spool.fails
    assert 0 < fails < spool_mod.MAX_FAILURES
    rec.close()
    s = TickSpool(tmp_path / "spool", utcnow=wall, clock=wall.mono)
    assert s.fails == fails and s.first_fail == wall.t.timestamp() - 9  # the first resend, at +1 s
    _, rec = _poison_run(tmp_path, wall, 300, rec=TickRecorder(_Poison(), spool=s), poison=False)
    assert rec.stats()["quarantined"] == 1


def test_a_graceful_stop_waits_for_the_flush_in_flight(tmp_path):
    """D15: compose stop cancels the drain loop, but a flush already in its worker thread keeps
    running. stash must wait for it, so the older in-doubt batch is spooled before the newer
    buffer and replay keeps time order."""
    import threading

    started, release = threading.Event(), threading.Event()

    class Dying:
        def write_ticks(self, frame):
            started.set()
            release.wait(5)
            raise RuntimeError("the q at the other end has gone away")

    rec = TickRecorder(Dying(), spool=TickSpool(tmp_path / "spool"))
    rec.record("BTC-USD", 1.0, 0.0, T0)
    flusher = threading.Thread(target=rec.flush)
    flusher.start()
    assert started.wait(5)
    rec.record("BTC-USD", 2.0, 0.0, T0 + timedelta(seconds=1))
    stasher = threading.Thread(target=rec.stash)
    stasher.start()
    stasher.join(0.3)
    assert stasher.is_alive(), "stash ran alongside the flush"
    release.set()
    flusher.join(5)
    stasher.join(5)
    s = TickSpool(tmp_path / "spool")
    rows = []
    while (seg := s.head(100)) is not None:
        rows += [r[2] for r in seg.rows]
        s.ack(seg)
    assert rows == [1.0, 2.0] and rec.dropped == 0


def test_replay_never_raises_when_the_cursor_cannot_be_saved(tmp_path, monkeypatch):
    """D16: a full disk makes _save_state raise; replay must still return, as documented."""
    store = _Poison()
    spool = TickSpool(tmp_path / "spool")
    spool.append([(T0, "BTC-USD", 1.0, 0.0)])
    rec = TickRecorder(store, spool=spool)

    def full(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(spool, "_save_state", full)
    assert rec.replay() == 0


def test_a_spool_file_name_is_never_reused(tmp_path, monkeypatch):
    """D16: if the cursor save fails after a finished file is deleted, the on-disk cursor still
    names that file at its old offset. A new file must not take the same name, or a restart
    would treat its first bytes as acknowledged and lose them."""
    s = TickSpool(tmp_path / "spool")
    s.append([(T0, "BTC-USD", float(i), 0.0) for i in range(5)])
    first = sorted(p.name for p in (tmp_path / "spool").glob("ticks_*"))[0]
    seg = s.head(100)
    real = s._save_state

    def full():  # the save in _finish_file, after the unlink
        raise OSError(28, "No space left on device")

    s.stage(seg)
    monkeypatch.setattr(s, "_save_state", full)
    with pytest.raises(OSError):
        s.ack(seg)
    monkeypatch.setattr(s, "_save_state", real)
    s.append([(T0, "ETH-USD", float(i), 0.0) for i in range(7)])
    names = sorted(p.name for p in (tmp_path / "spool").glob("ticks_*"))
    assert names and first not in names
    s.close()
    assert TickSpool(tmp_path / "spool").count == 7


def test_a_quarantined_file_moved_back_is_replayed_after_the_backlog_once(tmp_path):
    """Q3: the documented re-send. With a part-acknowledged backlog on disk, a quarantined file
    moved in as ticks_9999-12-31_000000.jsonl leaves the cursor where it was: nothing is sent
    twice, and the moved file comes last."""
    d = tmp_path / "spool"
    s = TickSpool(d)
    s.append([(T0, "BTC-USD", float(i), 0.0) for i in range(6)])
    seg = s.head(2)
    s.ack(seg)  # 0 and 1 are in kdb
    s.close()
    (d / "ticks_9999-12-31_000000.jsonl").write_bytes(encode((T0, "BTC-USD", -1.0, 0.0)))
    s = TickSpool(d)
    sent = []
    while (seg := s.head(100)) is not None:
        sent += [r[2] for r in seg.rows]
        s.ack(seg)
    assert sent == [2.0, 3.0, 4.0, 5.0, -1.0] and s.count == 0


def test_a_torn_kdb_log_backs_off_and_never_quarantines(tmp_path):
    """T1 (re-review 2026-10-17): while kdb's disk is full, persist.q refuses every upd with a
    `tlog:` error, applying nothing. That is a kdb outage, not a poison batch: the spool backs
    off as for a connection failure (1 s doubling to 15 s), counts no failure, and the batch
    lands first once the disk is back -- even after ten minutes."""
    wall = _Wall()
    healed = {"at": wall.t + timedelta(minutes=10)}
    attempts = []

    class Torn(_Poison):
        def write_ticks(self, frame):
            if wall.t < healed["at"]:
                attempts.append(wall.t)
                raise RuntimeError("tlog: torn; cut-back retried at most every 0D00:00:05")
            self.frames.append(frame)
            return len(frame)

    store = Torn()
    rec = TickRecorder(store, spool=TickSpool(tmp_path / "spool", utcnow=wall, clock=wall.mono))
    for i in range(1, 700):
        rec.record("BTC-USD", float(i), 0.0, T0 + timedelta(seconds=i))
        rec.flush()
        wall.tick(1)
    assert rec.stats()["quarantined"] == 0 and rec.spool.fails == 0 and rec.spooled == 0
    written = [p for f in store.frames for p in f["price"]]
    assert written == [float(i) for i in range(1, 700)]
    gaps = [(b - a).total_seconds() for a, b in zip(attempts, attempts[1:])]
    assert max(gaps) <= 16 and len(attempts) < 80  # backed off, capped like the session's
