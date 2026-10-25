# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""End-of-day flush: the kdb RDB surrenders the day's ticks to the Delta HDB.

The classic kdb+ day cycle (tickerplant -> RDB -> `.u.end` -> `.Q.hdpf` ->
HDB) mapped onto this stack:

    role         classic              here
    tickerplant  tick.q               the openbq-kdb service (v10/kdb/source/q/startup.q: upd+pub,
                                      plus persist.q's tick log + -11! replay)
    RDB          in-memory, g# syms   the SAME q -- trades is RAM-resident
    EOD flush    .u.end -> .Q.hdpf    this script: one UTC day -> Delta Lake,
                                      one Delta table per (ticker, day)
    HDB          date-partitioned     the Delta Lake store on S3 (RustFS on
                 splayed tables       openbq-docker), read back by live-grid's
                                      chart seam (app/lake.py) and anything
                                      that reads Delta
    RAM purge    .Q.hdpf deletes      NOT copied: live-grid's rolling window
                 tables, .Q.gc[]      prunes the cache on its own cadence --
                                      the chart's seam needs the trailing day

Idempotent per (symbol, day): the Delta key is `<SYM>_<YYYY_MM_DD>`, and a
re-run overwrites that table (a new Delta version) instead of duplicating --
unless the stored table already holds more of the day (D3: a restart's catch-up
reads a day the rolling window has partly pruned; see `_already_fuller`).
Runs in the openbq-lake image (Dockerfile.lake on openbq-docker), which carries
pykx, deltalake, openbb-deltalake and the DELTA_S3_* env every consumer of the
store reads. The IPC read
runs in a pykx-only subprocess: pykx and pyarrow's S3 client segfault when a
big IPC read and the object store share one process.

    python eod_dump.py --date 2026-08-28    # flush one UTC day, then exit
    python eod_dump.py --dry-run            # read kdb, print, write nothing
    python eod_dump.py --loop               # daily at 00:05 UTC, prior day
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("eod-dump")

LIBRARY = os.getenv("EOD_LIBRARY", "ticks_live")
# Which lake layer the durable copy lands in. "silver" resolves to the cold
# instance; the hot mirror keeps the last few sessions where the chart's seam
# reads them. Set EOD_HOT_SESSIONS=0 to write the durable copy only.
LAYER = os.getenv("EOD_LAYER", "silver")
HOT_LAYER = os.getenv("EOD_HOT_LAYER", "silver_hot")
HOT_LIBRARY = os.getenv("EOD_HOT_LIBRARY", "ticks_live_recent")
# openbq-docker v10: default 0. This line runs one store, so a "hot mirror"
# would be a second copy in the same bucket; the donor's default is 10.
HOT_SESSIONS = int(os.getenv("EOD_HOT_SESSIONS", "0"))
FLUSH_UTC_MINUTES = 5  # daily at 00:05 UTC, flushing the day that just ended
# A failed flush retries hourly. live-grid's LIVE_TICK_WINDOW_SECONDS (compose) must outlast the
# day plus the flush delay plus every retry, or the retries read a day already pruned (D3).
RETRY_ATTEMPTS = 20
RETRY_SLEEP_S = 3600


def _read_day_ipc(day: date):
    """The day's ticks over q IPC -- for a flush running ON the docker host,
    where the bridge (or the loopback publish) reaches q. Runs pykx in a
    child process (see module docstring) and hands the frame over as
    parquet; the read is chunked because a single >1M-row IPC message also
    segfaults pykx."""
    import subprocess
    import sys
    import tempfile

    import pandas as pd

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as fh:
        stage = fh.name
    try:
        subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--stage-day", str(day), stage],
            check=True,
        )
        return pd.read_parquet(stage)
    finally:
        try:
            os.unlink(stage)
        except OSError:
            pass


def _stage_day(day: date, out_path: str) -> None:
    """Child-process body: pykx only, chunked read, parquet out."""
    import pandas as pd
    import pykx as kx

    host = os.getenv("KDB_HOST", "kdb")
    port = int(os.getenv("KDB_PORT", "5000"))
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    chunk = 250_000
    q_count = "{[s;e] exec count i from trades where time within (s;e-1)}"
    # ponytail: the within-filter recomputes per chunk; fine at cache scale
    q_slice = (
        "{[s;e;o;n] n sublist o _ select time, sym, price, size from trades "
        "where time within (s;e-1)}"
    )
    with kx.SyncQConnection(host=host, port=port) as conn:
        s = kx.toq(start, kx.TimestampAtom)
        e = kx.toq(end, kx.TimestampAtom)
        n = int(conn(q_count, s, e).py())
        parts = [conn(q_slice, s, e, lo, chunk).pd() for lo in range(0, max(n, 1), chunk)]
    pd.concat(parts, ignore_index=True).to_parquet(out_path, index=False)


def read_day(day: date):
    """The day's ticks out of the RDB, as a pandas frame.

    openbq-docker v10: q IPC over the compose bridge only. The donor's
    KDB_HTTP_URL path (the NAS-side production flush over Serve's read-only
    HTTP) is not carried; nothing publishes kdb here.
    """
    return _read_day_ipc(day)


def store_configured(env=None) -> bool:
    """True when the flush has somewhere durable to write: all of DELTA_S3_*.

    openbq-docker v10: the flush writes by lake layer, and openbb-deltalake's
    `layer_target` falls back to a directory INSIDE the container when the
    DELTA_S3_* parts are missing (it does not read DELTA_URI). A nightly flush
    would then succeed into a path that disappears with the container, so the
    flush refuses instead (see main()).
    """
    e = os.environ if env is None else env
    return all(str(e.get(k, "")).strip() for k in (
        "DELTA_S3_ENDPOINT", "DELTA_S3_BUCKET", "DELTA_S3_ACCESS", "DELTA_S3_SECRET"))


def _already_fuller(s, key: str, df) -> bool:
    """True when the stored (sym, day) table holds more rows than `df`, or starts earlier.

    The kdb window is rolling, so re-reading a past day can return only its tail; that frame
    must not replace a complete flush. A missing table means write; any other read error is
    raised, so the flush fails and retries instead of guessing.
    """
    from deltalake import DeltaTable
    from deltalake.exceptions import TableNotFoundError

    try:
        old = DeltaTable(s._path(key), storage_options=s.storage_options).to_pyarrow_table(
            columns=["date"]).column("date").to_pandas()
    except TableNotFoundError:
        return False
    if old.empty:
        return False
    return len(old) > len(df) or old.min() < df["date"].min()


def dump_day(day: date, dry_run: bool = False) -> int:
    """Flush one UTC day to the HDB. Returns rows written."""
    frame = read_day(day)
    if frame.empty:
        log.info("%s: RDB holds no ticks for this day; nothing to flush", day)
        return 0

    total = 0
    groups = {str(sym): g for sym, g in frame.groupby("sym", observed=True) if len(g)}
    if dry_run:
        for sym, g in sorted(groups.items()):
            log.info("%s %-8s %6d ticks (dry run)", day, sym, len(g))
        return int(sum(len(g) for g in groups.values()))

    import re

    from openbb_deltalake import store as delta_store

    s = delta_store(layer=LAYER, library=LIBRARY)
    hot = None
    if HOT_SESSIONS > 0:
        try:
            hot = delta_store(layer=HOT_LAYER, library=HOT_LIBRARY)
        except Exception as exc:  # noqa: BLE001
            log.warning("hot mirror unavailable (%s); writing the durable copy only", exc)
    day_suffix = day.isoformat().replace("-", "_")
    for sym, g in sorted(groups.items()):
        df = g.drop(columns=["sym"]).rename(columns={"time": "date"})
        # one Delta table per (sym, day): a re-run overwrites the whole
        # table -- the idempotency .Q.hdpf gets from rewriting the partition
        key = re.sub(r"[^0-9A-Za-z_]", "_", sym) + "_" + day_suffix
        meta = {"source": "eod-dump", "sym": sym, "day": str(day)}
        if _already_fuller(s, key, df):
            log.warning("%s %-8s %6d ticks: the stored table holds more of the day; kept",
                        day, sym, len(df))
            continue
        info = s.write(key, df, metadata=meta)
        if hot is not None:
            # A mirror failure must not lose the flush: the durable copy above
            # already committed, and the mirror is a cache the next run rebuilds.
            try:
                hot.write(key, df, metadata=meta)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s %s: hot mirror write failed: %s", day, sym, exc)
        total += len(df)
        log.info(
            "%s %-8s %6d ticks -> %s/%s (delta v%s)",
            day, sym, len(df), LIBRARY, key, info.get("version"),
        )
    if hot is not None:
        _prune_hot_mirror(hot)
    log.info("%s: EOD complete, %d rows across %d symbols", day, total, len(groups))
    return total


def _prune_hot_mirror(hot) -> None:
    """Keep only the newest HOT_SESSIONS days in the hot mirror.

    Table keys are <SYM>_<YYYY_MM_DD>, so the day is the last three
    underscore-separated fields. Anything that does not parse is left alone
    rather than guessed at.
    """
    try:
        keys = list(hot.list_symbols())
    except Exception as exc:  # noqa: BLE001
        log.warning("hot mirror prune skipped, cannot list: %s", exc)
        return

    days: dict[str, list[str]] = {}
    for key in keys:
        parts = key.rsplit("_", 3)
        if len(parts) == 4 and all(p.isdigit() for p in parts[1:]):
            days.setdefault("_".join(parts[1:]), []).append(key)

    stale = sorted(days)[: max(0, len(days) - HOT_SESSIONS)]
    dropped = 0
    for day_key in stale:
        for key in days[day_key]:
            try:
                hot.delete(key)
                dropped += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("hot mirror prune failed for %s: %s", key, exc)
    if dropped:
        log.info(
            "hot mirror: dropped %d table(s) across %d day(s), keeping %d session(s)",
            dropped, len(stale), HOT_SESSIONS,
        )


def _sleep_until_next_flush() -> date:
    """Sleep to the next 00:05 UTC; return the day that will have just ended."""
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=0, minute=FLUSH_UTC_MINUTES, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    log.info("next flush at %s (in %ds)", nxt, int((nxt - now).total_seconds()))
    time.sleep((nxt - now).total_seconds())
    return (nxt - timedelta(days=1)).date()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="UTC day to flush (YYYY-MM-DD); default yesterday")
    parser.add_argument("--dry-run", action="store_true", help="read the RDB, write nothing")
    parser.add_argument("--loop", action="store_true", help="flush daily at 00:05 UTC")
    parser.add_argument("--stage-day", nargs=2, metavar=("DAY", "OUT"),
                        help=argparse.SUPPRESS)  # internal: pykx-only child process
    args = parser.parse_args()

    if args.stage_day:
        _stage_day(date.fromisoformat(args.stage_day[0]), args.stage_day[1])
        return

    if not args.dry_run and not store_configured():
        log.error("no Delta store configured: set DELTA_S3_* (rustfs.env)")
        raise SystemExit(2)

    if args.loop:
        # Catch-up before sleeping: a loop that starts after 00:05 (container
        # recreated, host rebooted) must not skip the day that already ended
        # while nobody was scheduled -- exactly how the first NAS flush was
        # missed. Idempotent, and a partial re-read never replaces a fuller
        # table, so re-flushing a covered day is harmless.
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        try:
            dump_day(yesterday)
        except Exception:  # noqa: BLE001 - catch-up is best-effort
            log.exception("catch-up flush failed for %s", yesterday)
        while True:
            day = _sleep_until_next_flush()
            # the RDB holds a rolling day, so a failed flush (the docker host
            # asleep at 00:05) still has its data for hours -- retry hourly
            # rather than surrendering the day to the prune
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    dump_day(day)
                    break
                except Exception:  # noqa: BLE001 - one bad day must not kill the cycle
                    log.exception(
                        "EOD flush failed for %s (attempt %d); retrying in 1h",
                        day, attempt + 1,
                    )
                    time.sleep(RETRY_SLEEP_S)
        return

    day = (
        date.fromisoformat(args.date)
        if args.date
        else (datetime.now(timezone.utc) - timedelta(days=1)).date()
    )
    dump_day(day, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
