# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""The on-disk tick spool: ticks kdb has not acknowledged, kept until it does.

User ruling (openbq-docker v10, 2026-10-12): ticks must be spooled to the
filesystem and recovered when a service restarts. The Mac crash drill had
live-grid drop ~100 s of crypto ticks while kdb was down; see
docs/v10/live-grid-kdb-port.md, "Tick spool and fast reconnect".

Layout, all under one directory on live-grid's persistent volume
(`/data/spool` by default, beside the watchlist):

- `ticks_<UTC date>_<seq>.jsonl` -- append-only, one tick per line, a compact JSON
  array `[iso time, sym, price, size]`, plus a fifth element (a batch id) on
  the lines of an IN-DOUBT batch: one whose write to kdb raised after it was
  sent, so it may already be in kdb. The date is the UTC date the tick was
  SPOOLED, not its own stamp, and `seq` (six digits) rises with every file
  opened that day -- at startup and at each roll (an eighth of the cap, at
  most 16 MB) -- so a lexical sort of the names is the spool's append order. JSON lines, not a binary format: ~70 bytes a tick
  (256 MB holds ~3.8 M ticks, ~44 h of the drill's 24 ticks/s), a torn
  final line is detectable and cut at load, and an operator can read it.
- `spool.state` -- the replay cursor `{"file", "offset", "inflight"}`:
  everything in `file` before byte `offset` is acknowledged by kdb;
  `inflight`, when set, is the end of the segment last sent and not yet
  confirmed. Replaced atomically (temp file, fsync, rename, fsync dir). It also
  keeps `seq`, `[UTC date, n]` for the last file opened, so a deleted file's
  name is never reused that day (D16: a cursor left naming a deleted file
  would otherwise skip the first bytes of its namesake), `fails`, how many
  sends of the head segment have raised (D5), and `first_fail`, the wall-clock
  time of the first of them (Q3).
- `quarantine/` -- segments whose send kept raising (a q error that recurs on
  every resend, such as a `'type` after a schema change). Resends back off
  exponentially (1 s doubling to 60 s), and a segment is moved here only after
  MAX_FAILURES sends spanning at least QUARANTINE_MIN_S of wall clock, so an
  error that clears (a full kdb-data disk freed) loses nothing. Moved, it is
  acknowledged and counted in `/health` (`ticks.quarantined`), so one poison
  batch cannot block every newer tick until the cap drops them. Same line
  format. To re-send one: stop live-grid, move the file into the spool
  directory as `ticks_9999-12-31_<six digits>.jsonl` (a name that sorts after
  every live file, so the replay cursor is undisturbed), start live-grid; it is
  replayed after the backlog, out of time order.

Durability. Appends are written through to the OS on every call, so a hard
kill of live-grid (SIGKILL, OOM) loses nothing that was appended. fsync runs
at most once per `fsync_interval` (LIVE_GRID_SPOOL_FSYNC_S, default 1 s),
from `append` or from `sync`, which the recorder calls on every 0.2 s flush:
a host crash or power loss can cost at most about the last second. The cursor
is fsynced on every change; it changes once per replayed segment, never per
tick.

Exactly once. A segment is staged (`inflight` persisted) BEFORE it is sent
and acknowledged (`offset` advanced) only AFTER kdb confirms the write. A
segment that may have reached kdb -- a staged one found at startup, or one
whose write raised anything but `KdbUnavailable` -- is in doubt, and the
recorder probes kdb (`KdbStore.ticks_present`) before sending it again. A
file is deleted only once every line in it is acknowledged.

Bounded. `max_bytes` (LIVE_GRID_SPOOL_MAX_MB, default 256) caps the files'
total size. Past it, new ticks are dropped and counted, never written, and a
warning is logged; an I/O error is the same. Nothing fills the disk silently.

Single-threaded by design: only `TickRecorder.flush` and, at shutdown,
`TickRecorder.stash` call in here, one at a time under the recorder's lock
(D15); `stats()`-style reads of the counters are plain ints.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

STATE_NAME = "spool.state"
PREFIX = "ticks_"
SUFFIX = ".jsonl"
DEFAULT_MAX_MB = 256
DEFAULT_FSYNC_S = 1.0
QUARANTINE = "quarantine"
# Raised sends of one segment before it is quarantined (D5), and the wall clock they must span
# (Q3): with the 1, 2, 4 .. 60 s backoff, 8 sends take about two minutes. A q that is merely
# down raises KdbUnavailable instead, which never counts.
MAX_FAILURES = 8
QUARANTINE_MIN_S = 60
BACKOFF_MAX_S = 60.0
# kdb refused a write without applying it (its tick log is torn, T1): the backoff a
# connection failure gets (openbq-kdb's KDB_RETRY_MAX_S), never counted toward quarantine.
DEFER_MAX_S = 15.0


@dataclass
class Segment:
    """A run of spooled ticks to replay as one kdb write."""

    file: str
    start: int
    end: int
    rows: list
    doubt: bool


def encode(row, batch: str | None = None) -> bytes:
    stamp, sym, price, size = row
    item = [stamp.isoformat(), sym, price, size]
    if batch is not None:
        item.append(batch)
    return (json.dumps(item, separators=(",", ":")) + "\n").encode()


def decode(line: bytes):
    """(row, batch id or None). Raises ValueError on a torn or foreign line."""
    item = json.loads(line)
    if not isinstance(item, list) or len(item) not in (4, 5):
        raise ValueError(f"not a spooled tick: {line[:80]!r}")
    row = (datetime.fromisoformat(item[0]), item[1], float(item[2]), float(item[3]))
    return row, (item[4] if len(item) == 5 else None)


class TickSpool:
    """Append-only tick files with a durable replay cursor. See the module docstring."""

    def __init__(self, directory, *, max_bytes: int = DEFAULT_MAX_MB * 2**20,
                 fsync_interval: float = DEFAULT_FSYNC_S, clock=time.monotonic,
                 utcnow=None):
        self.dir = Path(directory)
        self.max_bytes = int(max_bytes)
        self.fsync_interval = float(fsync_interval)
        self._clock = clock
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self.count = 0  # ticks on disk not yet acknowledged by kdb
        self.bytes = 0  # total size of the tick files
        self.dropped = 0  # ticks refused: over the cap, or an I/O error
        self._fh = None
        self._fh_name: str | None = None
        self._fh_size = 0
        self.roll_bytes = max(64 * 2**10, min(16 * 2**20, self.max_bytes // 8))
        self._dirty = False
        self._last_sync = clock()
        self._refusing = False  # log the first refusal of a run, not every one
        self._batch_seq = 0
        self._state = {"file": None, "offset": 0, "inflight": None}
        self._seq = None  # [day, n] of the last file opened; n only rises within a day (D16)
        self.fails = 0  # raised sends of the head segment (D5)
        self.first_fail = None  # wall-clock seconds of the first of them (Q3)
        self.retry_at = 0.0  # `clock` time before which the head is not resent (Q3; in memory)
        self._defers = 0  # consecutive refusals of the head (T1; in memory)
        self.quarantined = 0  # ticks moved to quarantine/
        self._load()

    # -- startup ---------------------------------------------------------------
    def _files(self) -> list[str]:
        try:
            names = os.listdir(self.dir)
        except FileNotFoundError:
            return []
        return sorted(n for n in names if n.startswith(PREFIX) and n.endswith(SUFFIX))

    def _load(self) -> None:
        """Recover what a previous process left: cut torn tails, count, read the cursor."""
        files = self._files()
        state_path = self.dir / STATE_NAME
        try:
            saved = json.loads(state_path.read_text())
            if isinstance(saved, dict):
                self._state.update({k: saved.get(k) for k in ("file", "offset", "inflight")})
                self._seq = saved.get("seq")
                self.fails = int(saved.get("fails") or 0)
                self.first_fail = saved.get("first_fail")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("tick spool: unreadable cursor %s (%s); replaying from the start", state_path, exc)
        if not files or self._state.get("file") != files[0]:
            self._state = {"file": files[0] if files else None, "offset": 0, "inflight": None}
            self.fails, self.first_fail = 0, None
        quarantine = self.dir / QUARANTINE
        if quarantine.is_dir():
            self.quarantined = sum(_count_lines(p, 0) for p in quarantine.iterdir() if p.is_file())
        self._state["offset"] = int(self._state.get("offset") or 0)
        for name in files:
            path = self.dir / name
            size = self._cut_torn_tail(path)
            start = self._state["offset"] if name == self._state["file"] else 0
            pending = _count_lines(path, min(start, size))
            if pending == 0:
                path.unlink()
                if name == self._state["file"]:
                    self._state = {"file": None, "offset": 0, "inflight": None}
                continue
            self.count += pending
            self.bytes += size
        files = self._files()
        if files and self._state["file"] != files[0]:
            self._state = {"file": files[0], "offset": 0, "inflight": None}
            self.fails, self.first_fail = 0, None
        if self.count:
            log.warning("tick spool: %d ticks left by a previous run in %s; replaying them first",
                        self.count, self.dir)

    def _cut_torn_tail(self, path: Path) -> int:
        """Truncate a final line the previous process died writing. Returns the size."""
        size = path.stat().st_size
        if size == 0:
            return 0
        with open(path, "r+b") as fh:
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return size
            # Find the last newline, reading backwards a block at a time.
            pos = size
            cut = 0
            while pos > 0:
                step = min(1 << 16, pos)
                pos -= step
                fh.seek(pos)
                block = fh.read(step)
                i = block.rfind(b"\n")
                if i >= 0:
                    cut = pos + i + 1
                    break
            fh.truncate(cut)
            os.fsync(fh.fileno())
        # It never reached the spool whole, so it is cut and counted dropped.
        self.dropped += 1
        log.warning("tick spool: cut a torn final line from %s", path.name)
        return cut

    # -- appending -------------------------------------------------------------
    @property
    def pending(self) -> bool:
        return self.count > 0

    def _handle(self, incoming: int):
        """The file to append `incoming` bytes to: today's newest, rolled by size.

        Files roll at `roll_bytes` (an eighth of the cap, at most 16 MB) so that
        replay frees disk a file at a time while the backlog drains, instead of
        only once one ever-growing file is fully acknowledged. Every new handle
        (startup, a new UTC day, a roll) starts a new, higher sequence number,
        so a lexical sort is always append order.
        """
        day = self._utcnow().strftime("%Y-%m-%d")
        if (self._fh is not None and self._fh_name.startswith(f"{PREFIX}{day}_")
                and (self._fh_size == 0 or self._fh_size + incoming <= self.roll_bytes)):
            return self._fh
        self._close_handle()
        self.dir.mkdir(parents=True, exist_ok=True)
        seqs = [int(n[len(PREFIX) + 11:-len(SUFFIX)]) for n in self._files()
                if n.startswith(f"{PREFIX}{day}_") and n[len(PREFIX) + 11:-len(SUFFIX)].isdigit()]
        # Past every name on disk AND every name used today (D16). Persisted before the file exists.
        used = self._seq[1] if isinstance(self._seq, list) and self._seq[0] == day else -1
        self._seq = [day, max([used] + seqs) + 1]
        self._save_state()
        name = f"{PREFIX}{day}_{self._seq[1]:06d}{SUFFIX}"
        self._fh = open(self.dir / name, "ab")
        self._fh_name = name
        self._fh_size = 0
        self._fsync_dir()
        if self._state["file"] is None:
            self._state = {"file": self._files()[0], "offset": 0, "inflight": None}
        return self._fh

    def _close_handle(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
        except OSError:
            log.debug("tick spool: error closing %s", self._fh_name, exc_info=True)
        self._fh = None
        self._fh_name = None
        self._dirty = False

    def _fsync_dir(self) -> None:
        try:
            fd = os.open(self.dir, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def new_batch_id(self) -> str:
        self._batch_seq += 1
        return f"{time.time_ns():x}-{self._batch_seq}"

    def append(self, rows, *, doubt: bool = False) -> int:
        """Spool `rows` (time, sym, price, size) in order. Returns how many were kept.

        `doubt=True` marks them as one in-doubt batch. Rows past the cap are
        dropped and counted, newest first, so the spool's order stays intact.
        """
        if not rows:
            return 0
        batch = self.new_batch_id() if doubt else None
        payload = [encode(r, batch) for r in rows]
        room = self.max_bytes - self.bytes
        keep = 0
        size = 0
        for line in payload:
            if size + len(line) > room:
                break
            size += len(line)
            keep += 1
        if keep < len(rows):
            self._refuse(len(rows) - keep, f"over the {self.max_bytes // 2**20} MB cap")
        if keep == 0:
            return 0
        fh = None
        try:
            fh = self._handle(size)
            fh.write(b"".join(payload[:keep]))
            fh.flush()  # through to the OS: a killed process loses nothing appended
        except OSError as exc:
            self._refuse(keep, f"I/O error: {exc}")
            if fh is not None:
                # Never leave a partial line for the next append to run into
                # (ENOSPC mid-write): cut the file back to its last whole line.
                try:
                    fh.truncate(self._fh_size)
                except (OSError, ValueError):
                    log.debug("tick spool: could not cut back %s", self._fh_name, exc_info=True)
            self._close_handle()
            return 0
        self._fh_size += size
        self.count += keep
        self.bytes += size
        self._dirty = True
        if keep == len(rows):
            self._refusing = False
        self.sync()
        return keep

    def _refuse(self, n: int, why: str) -> None:
        self.dropped += n
        if not self._refusing:
            log.warning("tick spool %s: dropping ticks (%s); %d dropped so far",
                        self.dir, why, self.dropped)
        self._refusing = True

    def sync(self, force: bool = False) -> bool:
        """fsync the open file if it has unsynced appends and the interval is up."""
        if self._fh is None or not self._dirty:
            return False
        now = self._clock()
        if not force and now - self._last_sync < self.fsync_interval:
            return False
        try:
            os.fsync(self._fh.fileno())
        except OSError:
            log.warning("tick spool: fsync failed", exc_info=True)
            return False
        self._dirty = False
        self._last_sync = now
        return True

    # -- replay ----------------------------------------------------------------
    def head(self, max_rows: int) -> Segment | None:
        """The next segment to replay, oldest first, or None when empty.

        A staged (`inflight`) segment is returned exactly as it was staged and
        marked in doubt. Otherwise a segment is a run of up to `max_rows` plain
        lines, or one whole in-doubt batch (never mixed, never split).
        """
        name = self._state["file"]
        if name is None:
            if self.count:
                log.warning("tick spool: %d ticks counted but no file holds them", self.count)
                self.count = 0
            return None
        if not self.count:
            return None
        if self._fh is not None:
            self._fh.flush()
        path = self.dir / name
        offset = self._state["offset"]
        inflight = self._state["inflight"]
        rows: list = []
        end = offset
        batch_of_run = None
        with open(path, "rb") as fh:
            fh.seek(offset)
            while True:
                if inflight is not None and end >= inflight:
                    break
                line = fh.readline()
                if not line or not line.endswith(b"\n"):
                    break
                try:
                    row, batch = decode(line)
                except (ValueError, TypeError) as exc:
                    # Unreadable mid-file (disk damage, a foreign edit): it can
                    # never be replayed, so it is acknowledged past and counted.
                    log.warning("tick spool: skipping an unreadable line in %s: %s", name, exc)
                    if rows:
                        break
                    end += len(line)
                    self.dropped += 1
                    self.count -= 1
                    self._advance(name, end)
                    offset = end
                    continue
                if inflight is None:
                    if not rows:
                        batch_of_run = batch
                    elif batch != batch_of_run:
                        break
                    if batch is None and len(rows) >= max_rows:
                        break
                rows.append(row)
                end += len(line)
        if not rows:
            if self.count and self._state["file"] == name and end >= path.stat().st_size:
                self._finish_file(name)
                return self.head(max_rows)
            return None
        doubt = inflight is not None or batch_of_run is not None
        return Segment(name, offset, end, rows, doubt)

    def stage(self, seg: Segment) -> None:
        """Persist that `seg` is about to be sent (before any byte goes to kdb)."""
        if self._state["inflight"] != seg.end:
            self._state["inflight"] = seg.end
            self._save_state()

    def unstage(self) -> None:
        """The send provably never reached kdb (`KdbUnavailable`): not in doubt."""
        if self._state["inflight"] is not None:
            self._state["inflight"] = None
            self._save_state()

    def ack(self, seg: Segment) -> None:
        """kdb confirmed `seg` (or already held it): advance past it, delete a finished file."""
        self.count -= len(seg.rows)
        self._advance(seg.file, seg.end)

    def fail(self) -> bool:
        """A send of the head segment raised: back off. True once it has failed MAX_FAILURES
        times over at least QUARANTINE_MIN_S of wall clock (Q3)."""
        now = self._utcnow().timestamp()
        if not self.fails or self.first_fail is None:
            self.first_fail = now
        self.fails += 1
        self.retry_at = self._clock() + min(BACKOFF_MAX_S, 2.0 ** (self.fails - 1))
        self._save_state()
        return self.fails >= MAX_FAILURES and now - self.first_fail >= QUARANTINE_MIN_S

    def backing_off(self) -> bool:
        """True while a failed head segment waits for its next try."""
        return self._clock() < self.retry_at

    def defer(self) -> None:
        """kdb refused the head without applying it (T1): back off 1 s doubling to
        DEFER_MAX_S, like a connection failure. No failure is counted."""
        self._defers += 1
        self.retry_at = self._clock() + min(DEFER_MAX_S, 2.0 ** (self._defers - 1))

    def quarantine(self, seg: Segment) -> None:
        """Move `seg` to quarantine/ (fsynced) and acknowledge it, so replay moves on."""
        qdir = self.dir / QUARANTINE
        qdir.mkdir(parents=True, exist_ok=True)
        with open(qdir / seg.file, "ab") as fh:
            fh.write(b"".join(encode(r) for r in seg.rows))
            fh.flush()
            os.fsync(fh.fileno())
        self.quarantined += len(seg.rows)
        self.ack(seg)

    def _advance(self, name: str, end: int) -> None:
        self.fails, self.first_fail, self.retry_at, self._defers = 0, None, 0.0, 0
        self._state = {"file": name, "offset": end, "inflight": None}
        path = self.dir / name
        size = path.stat().st_size if path.exists() else end
        if end >= size:
            self._finish_file(name)
        else:
            self._save_state()

    def _finish_file(self, name: str) -> None:
        """Every line in `name` is acknowledged: delete it, move the cursor on."""
        if self._fh_name == name:
            self._close_handle()
        path = self.dir / name
        try:
            size = path.stat().st_size
            path.unlink()
            self.bytes -= size
        except FileNotFoundError:
            pass
        rest = self._files()
        self._state = {"file": rest[0] if rest else None, "offset": 0, "inflight": None}
        self._save_state()
        self._fsync_dir()

    def _save_state(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (STATE_NAME + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dict(self._state, seq=self._seq, fails=self.fails, first_fail=self.first_fail), fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.dir / STATE_NAME)
        self._fsync_dir()

    def close(self) -> None:
        self._close_handle()


def _count_lines(path: Path, start: int) -> int:
    """Newlines in `path` from byte `start`, streamed (a spool can be hundreds of MB)."""
    n = 0
    with open(path, "rb") as fh:
        fh.seek(start)
        while block := fh.read(1 << 20):
            n += block.count(b"\n")
    return n


def from_env(watchlist_path: str) -> TickSpool:
    """The spool as docker-compose.yml configures it (see live-grid/README.md)."""
    directory = (os.getenv("LIVE_GRID_SPOOL_DIR") or "").strip() or os.path.join(
        os.path.dirname(watchlist_path) or ".", "spool")
    max_mb = _env_number("LIVE_GRID_SPOOL_MAX_MB", DEFAULT_MAX_MB)
    fsync_s = _env_number("LIVE_GRID_SPOOL_FSYNC_S", DEFAULT_FSYNC_S)
    return TickSpool(directory, max_bytes=int(max_mb * 2**20), fsync_interval=fsync_s)


def _env_number(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default
    if not value >= 0:
        log.warning("%s=%r is negative; using %s", name, raw, default)
        return default
    return value
