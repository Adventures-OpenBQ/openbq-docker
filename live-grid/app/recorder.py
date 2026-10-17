# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Buffering ticks for batched writes into kdb.

Per-tick IPC cannot keep up with a live feed, so ticks accumulate here and are
written as one batch per flush. The buffer is bounded: when q is unreachable an
unbounded buffer would grow until the process died, which is a worse failure
than losing ticks a cache was never promised to keep.

With a `TickSpool` (openbq-docker v10, user ruling 2026-10-12: ticks must be
spooled to the filesystem and recovered when a service restarts), a batch kdb
did not acknowledge is not dropped but appended to the spool on live-grid's
volume, and every flush replays the spool into kdb, oldest first, BEFORE any
newer tick: while the spool holds anything, new batches go to its tail, not
to kdb. A batch whose write raised after it was sent is in doubt; it is
probed (`KdbStore.ticks_present`) before it is sent again, so it never lands
twice. See app/spool.py and docs/v10/live-grid-kdb-port.md ("Tick spool and
fast reconnect"). Without a spool (the class's library default, which the
donor's tests pin) a failed batch is dropped and counted, as before.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Ticks per replayed kdb write: one IPC round trip, a few hundred KB.
REPLAY_BATCH = 5000
# Time one flush may spend replaying before it hands control back to the drain
# loop (which awaits the flush, so a long replay would stall quote draining).
# At least one segment is always attempted.
REPLAY_BUDGET_S = 1.0

COLUMNS = ["time", "sym", "price", "size"]


def _refused(exc) -> bool:
    """kdb refused the write and applied nothing: persist.q's torn-log signals start "tlog: "
    (T1). Its disk is the problem, not the batch, so this is an outage, never quarantine."""
    return str(exc).startswith("tlog: ")


def _unavailable_type():
    try:
        from openbq_kdb.session import KdbUnavailable
    except ImportError:  # pragma: no cover - openbq-kdb is a hard dependency in the image
        return ()
    return KdbUnavailable


class TickRecorder:
    """A bounded tick buffer with batched writes, a disk spool and a rolling-window prune."""

    def __init__(self, store, max_buffer: int = 100_000, window: timedelta = timedelta(days=1),
                 spool=None, clock=time.monotonic):
        self.store = store
        self.window = window
        self.spool = spool
        self._clock = clock
        self._buf: deque = deque(maxlen=max_buffer)
        self._lost = 0  # buffer overflow, and failed batches when there is no spool
        self.written = 0  # ticks kdb confirmed, live and replayed
        self.replayed = 0  # of those, ticks that came from the spool
        self.deduped = 0  # in-doubt ticks kdb already held, so not sent again
        self._unavailable = _unavailable_type()
        # D15: flush runs on a worker thread that cancelling the drain loop does not stop, so
        # stash (shutdown) waits for it here instead of spooling the newer buffer first.
        self._lock = threading.Lock()

    @property
    def buffered(self) -> int:
        return len(self._buf)

    @property
    def dropped(self) -> int:
        """Ticks truly lost: buffer overflow, the spool's cap or I/O errors, or
        (with no spool) a failed batch. A spooled tick is not dropped."""
        return self._lost + (self.spool.dropped if self.spool is not None else 0)

    @property
    def spooled(self) -> int:
        return self.spool.count if self.spool is not None else 0

    def record(self, sym: str, price: float, size, stamp: datetime) -> None:
        """Append one tick. Oldest is dropped when the buffer is full."""
        if len(self._buf) == self._buf.maxlen:
            self._lost += 1
        self._buf.append((stamp, sym, float(price), float(size) if size is not None else 0.0))

    @staticmethod
    def _frame_of(rows):
        import pandas as pd

        return pd.DataFrame(rows, columns=COLUMNS)

    def _frame(self):
        return self._frame_of(list(self._buf))

    def _take(self) -> list:
        """Move the buffer's current contents out, oldest first.

        `record()` runs on the event loop while `flush()` runs on a worker
        thread. Copying the deque and then clearing it would silently discard
        any tick appended between the two; popping exactly the ticks taken
        cannot (deque.popleft is atomic under the GIL).
        """
        batch = []
        for _ in range(len(self._buf)):
            try:
                batch.append(self._buf.popleft())
            except IndexError:
                break
        return batch

    def flush(self) -> int:
        """Write the buffer as one batch (after any spooled backlog). Returns rows written."""
        with self._lock:
            return self._flush()

    def _flush(self) -> int:
        batch = self._take()
        if self.spool is None:
            return self._flush_without_spool(batch)
        self.spool.sync()
        if self.spool.pending:
            # Order: everything already spooled goes to kdb before these.
            self.spool.append(batch)
            return self.replay()
        if not batch:
            return 0
        try:
            written = self.store.write_ticks(self._frame_of(batch))
        except self._unavailable as exc:
            # Raised before anything was sent: these ticks are certainly not in kdb.
            log.info("kdb unavailable, spooling %d ticks: %s", len(batch), exc)
            self.spool.append(batch)
            return 0
        except Exception as exc:  # noqa: BLE001 - a cache write must not kill the feed
            if _refused(exc):
                # T1: q signalled before applying anything, so certainly not in kdb.
                log.info("kdb refused the write (its tick log), spooling %d ticks: %s",
                         len(batch), exc)
                self.spool.append(batch)
                self.spool.defer()
                return 0
            log.warning("tick flush failed after sending, spooling %d ticks as in doubt: %s",
                        len(batch), exc)
            self.spool.append(batch, doubt=True)
            return 0
        self.written += written
        return written

    def _flush_without_spool(self, batch) -> int:
        if not batch:
            return 0
        frame = self._frame_of(batch)
        try:
            written = self.store.write_ticks(frame)
        except Exception as exc:  # noqa: BLE001 - a cache write must not kill the feed
            log.warning("tick flush failed, dropping %d buffered ticks: %s", len(frame), exc)
            self._lost += len(frame)
            return 0
        self.written += written
        return written

    def _backing_off(self) -> bool:
        session = getattr(self.store, "session", None)
        retry_in = getattr(session, "retry_in", None)
        try:
            return bool(retry_in and retry_in() > 0)
        except Exception:  # noqa: BLE001
            return False

    def replay(self) -> int:
        """Send the spool to kdb, oldest first, until it is empty, kdb fails, or the
        time budget is spent. Returns ticks written. Never raises.

        Each segment is staged on disk before it is sent and acknowledged only
        after kdb confirms it. An in-doubt segment is probed first and skipped
        (acknowledged, counted `deduped`) when kdb already holds every row.
        """
        spool = self.spool
        if spool is None or not spool.pending or self._backing_off() or spool.backing_off():
            return 0
        try:
            return self._replay(spool)
        except OSError as exc:  # D16: the cursor cannot be saved (disk full); retry next flush
            log.warning("tick spool: replay stopped, cannot save the cursor: %s", exc)
            return 0

    def _replay(self, spool) -> int:
        deadline = self._clock() + REPLAY_BUDGET_S
        total = 0
        while spool.pending:
            try:
                seg = spool.head(REPLAY_BATCH)
            except OSError as exc:
                log.warning("tick spool unreadable: %s", exc)
                return total
            if seg is None:
                break
            frame = self._frame_of(seg.rows)
            if seg.doubt:
                try:
                    present = self.store.ticks_present(frame)
                except Exception as exc:  # noqa: BLE001 - try again on a later flush
                    log.info("tick spool: cannot probe an in-doubt segment yet: %s", exc)
                    return total
                if present >= len(seg.rows):
                    spool.ack(seg)
                    self.deduped += len(seg.rows)
                    log.info("tick spool: kdb already held %d in-doubt ticks; not resent",
                             len(seg.rows))
                    continue
            spool.stage(seg)
            try:
                written = self.store.write_ticks(frame)
            except self._unavailable as exc:
                if not seg.doubt:
                    spool.unstage()  # nothing was sent: not in doubt
                log.info("tick spool: kdb unavailable, %d ticks wait: %s", spool.count, exc)
                return total
            except Exception as exc:  # noqa: BLE001 - stays staged: in doubt next time
                if _refused(exc):
                    # T1: a kdb outage (its disk), not a poison batch: back off, count nothing.
                    if not seg.doubt:
                        spool.unstage()  # q applied nothing: not in doubt
                    spool.defer()
                    log.info("tick spool: kdb refused the write, %d ticks wait: %s",
                             spool.count, exc)
                    return total
                if spool.fail():
                    # D5/Q3: the same error on every resend, for over a minute of backoff;
                    # set it aside rather than block.
                    sends = spool.fails
                    spool.quarantine(seg)
                    log.warning("tick spool: quarantined %d ticks after %d failed sends: %s",
                                len(seg.rows), sends, exc)
                    continue
                # Warn once per segment; the retries every 0.2 s would flood the log.
                (log.warning if spool.fails == 1 else log.debug)(
                    "tick spool: replay write failed after sending: %s", exc)
                return total
            spool.ack(seg)
            self.written += written
            self.replayed += written
            total += written
            if self._clock() >= deadline:
                break
        if total:
            log.info("tick spool: replayed %d ticks; %d still spooled", total, spool.count)
        return total

    def prune(self, now: datetime | None = None) -> int:
        """Drop ticks older than the rolling window. Never raises."""
        cutoff = (now or datetime.now()) - self.window
        try:
            return self.store.prune_ticks(cutoff)
        except Exception as exc:  # noqa: BLE001
            log.warning("tick prune failed: %s", exc)
            return 0

    def stats(self) -> dict:
        """Counters for /health."""
        return {
            "buffered": self.buffered,
            "written": self.written,
            "dropped": self.dropped,
            "spooled": self.spooled,
            "replayed": self.replayed,
            "deduped": self.deduped,
            "quarantined": self.spool.quarantined if self.spool is not None else 0,
        }

    def stash(self) -> int:
        """At shutdown: move the unflushed buffer to the spool (no kdb call) and
        fsync. The next process replays it. Returns ticks spooled. Never raises."""
        if self.spool is None:
            return 0
        try:
            with self._lock:
                kept = self.spool.append(self._take())
            self.spool.close()
            return kept
        except Exception:  # noqa: BLE001 - shutdown must finish
            log.warning("tick spool: could not stash the buffer at shutdown", exc_info=True)
            return 0

    def close(self) -> None:
        if self.spool is not None:
            self.spool.close()
