# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Reading flushed ticks back from the Delta Lake store, for the chart seam.

openbq-docker v10 (user ruling 2026-10-12: the S3 tier moves into v10). The
nightly eod-dump (scripts/eod_dump.py, from the donor line) writes each UTC day kdb
held into one Delta table per (symbol, day), `<library>/<SYM>_<YYYY_MM_DD>`.
kdb itself keeps only a rolling window (LIVE_TICK_WINDOW_SECONDS), so without
this module a 1m chart over last week is provider history even though the
ticks for those days are sitting in the store.

The join is at UTC day edges, which is where the flush cuts:

- a whole PAST UTC day the store holds is served from its flushed ticks;
- kdb's ticks own only what lies after the last such day (and, as before, only
  from the first bar they fully cover);
- history fills everything neither covers.

A bar never straddles a day edge because only intervals that divide a day
evenly use the store (1m, 5m, 15m, 1h, ...). Any failure reading the store
degrades to the kdb-only answer: a store outage never blanks a chart.

The connection is openbb-deltalake's DELTA_S3_* contract (utils.py,
`s3_options_from_env`, from the donor line), re-stated here so live-grid does not
import openbb-core. A missing part disables the read-back; there is no local
fallback directory, unlike openbb-deltalake's (a container path would read as
"no flushed days" forever). DELTA_URI (a local path) is honoured for tests and
a store without S3.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

_S3_REQUIRED = ("DELTA_S3_ENDPOINT", "DELTA_S3_BUCKET", "DELTA_S3_ACCESS", "DELTA_S3_SECRET")
DAY = timedelta(days=1)
_EPOCH = datetime(1970, 1, 1)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def resolve(env=None):
    """(base_uri, storage_options), or None when no store is configured."""
    e = os.environ if env is None else env
    if all(str(e.get(k, "")).strip() for k in _S3_REQUIRED):
        port = str(e.get("DELTA_S3_PORT") or "9000").strip()
        secure = str(e.get("DELTA_S3_SECURE") or "true").strip().lower()
        if not port.isdigit() or secure not in ("true", "false"):
            raise ValueError("DELTA_S3_PORT must be a number and DELTA_S3_SECURE true/false")
        scheme = "https" if secure == "true" else "http"
        options = {
            "aws_endpoint": f"{scheme}://{str(e['DELTA_S3_ENDPOINT']).strip()}:{port}",
            "aws_access_key_id": str(e["DELTA_S3_ACCESS"]).strip(),
            "aws_secret_access_key": str(e["DELTA_S3_SECRET"]).strip(),
            "aws_region": "us-east-1",
            "aws_virtual_hosted_style_request": "false",
            "aws_conditional_put": "etag",
        }
        if scheme == "http":
            options["aws_allow_http"] = "true"
        return f"s3://{str(e['DELTA_S3_BUCKET']).strip()}", options
    uri = str(e.get("DELTA_URI", "")).strip().rstrip("/")
    if uri and not uri.startswith("s3://"):
        return uri, {}
    return None


def table_key(symbol: str, day: date) -> str:
    """eod_dump.py's key: `<SYM>_<YYYY_MM_DD>`, punctuation to `_`."""
    return re.sub(r"[^0-9A-Za-z_]", "_", symbol) + "_" + day.isoformat().replace("-", "_")


def day_aligned(interval: str) -> bool:
    """True for an intraday interval whose buckets tile a UTC day exactly.

    `1d` and wider stay on provider history: a flushed day holds only what the
    recorder saw, so a daily bar built from it could silently be a partial day.
    """
    from openbq_kdb.aggregate import bucket_ns

    try:
        width = bucket_ns(interval)
    except ValueError:
        return False
    day_ns = 86_400 * 10**9
    return width < day_ns and day_ns % width == 0


def day_span(ticks, interval: str):
    """The span one flushed day's ticks own: from the first bucket they FULLY
    cover (the seam rule, app.series.seam_boundary) to the end of the bucket
    holding the last tick. Recording that began mid-morning leaves the morning
    to history instead of dropping it."""
    import pandas as pd
    from openbq_kdb.aggregate import bucket_ns

    from app.series import seam_boundary

    first = pd.Timestamp(ticks["time"].iloc[0]).to_pydatetime()
    last = pd.Timestamp(ticks["time"].iloc[-1]).to_pydatetime()
    width = timedelta(microseconds=bucket_ns(interval) / 1000)
    lo = seam_boundary(first, interval)
    hi = _EPOCH + ((last - _EPOCH) // width + 1) * width
    return lo, hi


class LakeTicks:
    """Read-only access to eod-dump's `<library>/<SYM>_<YYYY_MM_DD>` tables."""

    def __init__(self, base: str, storage_options: dict, library: str = "ticks_live",
                 max_days: int = 10):
        self.base = base.rstrip("/")
        self.storage_options = storage_options
        self.library = library
        self.max_days = max_days

    @classmethod
    def from_env(cls, env=None):
        """The reader the compose environment asks for, or None."""
        e = os.environ if env is None else env
        if not _truthy(e.get("LIVE_GRID_LAKE_READBACK")):
            return None
        try:
            target = resolve(e)
        except ValueError as exc:
            log.warning("lake read-back disabled: %s", exc)
            return None
        if target is None:
            log.info("lake read-back disabled: DELTA_S3_* is not set")
            return None
        library = str(e.get("LIVE_GRID_LAKE_LIBRARY") or "ticks_live").strip()
        max_days = int(str(e.get("LIVE_GRID_LAKE_MAX_DAYS") or "10").strip())
        return cls(target[0], target[1], library=library, max_days=max_days)

    def path(self, symbol: str, day: date) -> str:
        return f"{self.base}/{self.library}/{table_key(symbol, day)}"

    def read_day(self, symbol: str, day: date):
        """That day's flushed ticks (time, price, size), time-sorted, or None."""
        from deltalake import DeltaTable
        from deltalake.exceptions import TableNotFoundError

        path = self.path(symbol, day)
        # Open and catch, rather than DeltaTable.is_deltatable: on deltalake 1.6.6
        # is_deltatable never returned against an S3 endpoint in testing (moto),
        # while opening a missing table raises TableNotFoundError at once.
        try:
            table = DeltaTable(path, storage_options=self.storage_options)
        except TableNotFoundError:
            return None
        frame = table.to_pandas(columns=["date", "price", "size"])
        if frame.empty:
            return None
        import pandas as pd

        frame = frame.rename(columns={"date": "time"})
        frame["time"] = pd.to_datetime(frame["time"])
        if getattr(frame["time"].dt, "tz", None) is not None:
            frame["time"] = frame["time"].dt.tz_convert("UTC").dt.tz_localize(None)
        return frame.sort_values("time", kind="stable").reset_index(drop=True)

    def wanted_days(self, start: str, end: str, today: date) -> list[date]:
        """Whole past UTC days inside the request, newest `max_days` at most."""
        from app.series import window_end

        try:
            lo = datetime.fromisoformat(str(start).strip()[:10]).date()
        except ValueError:
            return []
        hi_end = window_end(end)
        hi = today - DAY if hi_end == datetime.max else min(hi_end.date(), today - DAY)
        lo = max(lo, today - timedelta(days=self.max_days))
        days, day = [], lo
        while day <= hi:
            days.append(day)
            day += DAY
        return days


def bars(ticks, interval: str) -> list[dict]:
    """OHLCV + trade-true vwap per bucket, as openbq-kdb's aggregate_ticks returns
    them: `width xbar time` on time-sorted ticks; a bucket with no traded size has
    vwap None ("no trade data"), never a fabricated value."""
    import math

    import pandas as pd
    from openbq_kdb.aggregate import bucket_ns

    if ticks is None or not len(ticks):
        return []
    width = bucket_ns(interval)
    ns = pd.to_datetime(ticks["time"]).astype("datetime64[ns]").astype("int64")
    frame = ticks.assign(t=(ns // width) * width, pv=ticks["price"] * ticks["size"])
    grouped = frame.groupby("t", sort=True)
    out = pd.DataFrame({
        "open": grouped["price"].first(), "high": grouped["price"].max(),
        "low": grouped["price"].min(), "close": grouped["price"].last(),
        "volume": grouped["size"].sum(), "pv": grouped["pv"].sum(),
    }).reset_index()
    rows = []
    for row in out.itertuples():
        vwap = row.pv / row.volume if row.volume else float("nan")
        rows.append({
            "date": _EPOCH + timedelta(microseconds=int(row.t) // 1000),
            "open": float(row.open), "high": float(row.high),
            "low": float(row.low), "close": float(row.close),
            "volume": float(row.volume),
            "vwap": None if math.isnan(vwap) else float(vwap),
        })
    return rows


def join(history: list[dict], lake_rows: list[dict], lake_spans: list[tuple],
         tick_rows: list[dict], tick_boundary: datetime | None) -> list[dict]:
    """History, flushed-day bars and kdb tick bars, each owning its own span.

    Each flushed day owns its `day_span`; kdb's bars own [tick_boundary, ...).
    A history row is kept only where nothing else owns it.
    """
    spans = list(lake_spans)
    if tick_rows and tick_boundary is not None:
        spans.append((tick_boundary, datetime.max))
    from app.series import _row_dt

    kept = [row for row in history
            if not any(lo <= _row_dt(row["date"]) < hi for lo, hi in spans)]
    return sorted(kept + list(lake_rows) + list(tick_rows), key=lambda r: _row_dt(r["date"]))


async def series_with_lake(symbol, interval, start, end, recorder, window, history, meta, lake,
                           today: date | None = None):
    """build_series' path when the store is configured (see the module docstring)."""
    import asyncio
    from datetime import timezone

    from app.series import seam_boundary, tick_capable, window_end

    today = today or datetime.now(timezone.utc).date()
    meta["rows_from_lake"] = 0
    meta["lake_days"] = []
    lake_rows: list[dict] = []
    spans: list[tuple] = []
    days: list[date] = []
    try:
        for day in lake.wanted_days(start, end, today):
            ticks = await asyncio.to_thread(lake.read_day, symbol, day)
            if ticks is None:
                continue
            lo, hi = day_span(ticks, interval)
            rows = [r for r in bars(ticks, interval) if lo <= r["date"] < hi]
            if rows:
                days.append(day)
                spans.append((lo, hi))
                lake_rows.extend(rows)
    except Exception as exc:  # noqa: BLE001 - a store outage degrades to kdb + history
        log.warning("lake read-back unavailable for %s: %s", symbol, exc)
        lake_rows, spans, days = [], [], []

    tick_rows: list[dict] = []
    boundary = None
    if recorder is not None and tick_capable(interval, window):
        try:
            from openbq_kdb.aggregate import aggregate_ticks

            span = await asyncio.to_thread(recorder.store.tick_span, symbol)
            if span is not None:
                boundary = seam_boundary(span[0], interval)
                if spans:
                    boundary = max(boundary, max(hi for _, hi in spans))
                hi = min(span[1], window_end(end))
                if hi >= boundary:
                    tick_rows = await asyncio.to_thread(
                        aggregate_ticks, recorder.store, symbol, interval, boundary, hi)
        except Exception as exc:  # noqa: BLE001 - the chart still works without ticks
            log.warning("tick aggregation unavailable for %s: %s", symbol, exc)
            tick_rows = []

    if tick_rows:
        meta["rows_from_ticks"] = len(tick_rows)
        meta["seam"] = boundary.isoformat()
    meta["rows_from_lake"] = len(lake_rows)
    meta["lake_days"] = [d.isoformat() for d in days]
    if not lake_rows and not tick_rows:
        return history, meta
    return join(history, lake_rows, spans, tick_rows, boundary if tick_rows else None), meta
