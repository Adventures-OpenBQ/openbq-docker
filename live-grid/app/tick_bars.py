# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""`GET /ticks?interval=`: bars from the ticks live-grid holds, and nothing else.

The live-composed-bars spec §4 (arts-charts-openbq): arts_charts stitches its own
history, so this answer is the tick plane alone -- kdb's rolling window plus, for a
`start` before it, the days eod-dump flushed to the lake (app/lake.py), joined at
the same seam `/series` uses. It never calls `fetch_series`: no EODHD or openbq-api
request is made, whatever the window.

`span` is kdb's first and last tick for the symbol, or None when kdb holds none. It
describes the rolling store, not the lake: a caller compares `span.first` with a
session open to see whether a restart left a gap (spec L9), and a flushed day
before the restart must not hide that gap.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

#: The most bars one answer carries. A 1m day is 1,440 and the lake reads back at
#: most LIVE_GRID_LAKE_MAX_DAYS (default 10) days, so 1m over the whole reachable
#: window fits; a seconds-wide interval over days does not, and is refused rather
#: than truncated (a cut answer would read as a gap).
MAX_BARS = 20_000


class TicksRequestError(Exception):
    """A request the route answers with 422."""


def parse_start(raw: str) -> datetime:
    """`start` as a naive UTC datetime: a date is its UTC midnight, a naive datetime
    is UTC, an offset is converted. Raises TicksRequestError."""
    text = str(raw).strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), datetime.min.time())
        at = datetime.fromisoformat(text)
    except ValueError:
        raise TicksRequestError(
            f"start {raw!r} is not an ISO date or datetime (YYYY-MM-DD, or "
            "YYYY-MM-DDTHH:MM:SS with Z or an offset; a '+' in a URL is %2B)") from None
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    return at


def iso_utc(at) -> str:
    """A naive-UTC (or aware) datetime as ISO with `Z`."""
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    return at.isoformat() + "Z"


async def tick_bars(symbol: str, interval: str, start: str | None, recorder, lake,
                    today: date | None = None) -> dict:
    """`{symbol, interval, bars, span}` (see the module docstring).

    Raises TicksRequestError for an interval the ticks cannot build, a bad `start` or an
    answer over MAX_BARS; any other exception (a kdb IPC or lake read failure) propagates
    for the route to answer 503."""
    from openbq_kdb.aggregate import bucket_ns

    from app.lake import day_aligned, kdb_bars, lake_bars
    from app.series import _row_dt, seam_boundary, tick_capable

    try:
        bucket_ns(interval)
    except ValueError as exc:
        raise TicksRequestError(str(exc)) from None
    if recorder is not None and not tick_capable(interval, recorder.window):
        raise TicksRequestError(
            f"interval {interval!r} is wider than the {recorder.window} of ticks held")
    lo = seam_boundary(parse_start(start), interval) if start else None
    today = today or datetime.now(timezone.utc).date()

    lake_rows: list[dict] = []
    lake_end = None
    if lake is not None and lo is not None and day_aligned(interval):
        rows, spans, _ = await lake_bars(lake, symbol, interval, lo.isoformat(),
                                         today.isoformat(), today)
        lake_rows = [r for r in rows if r["date"] >= lo]
        lake_end = max((hi for _, hi in spans), default=None)

    kdb_rows: list[dict] = []
    span = None
    if recorder is not None:
        after = max((t for t in (lo, lake_end) if t is not None), default=None)
        kdb_rows, _, span = await kdb_bars(recorder.store, symbol, interval, after,
                                           datetime.max)

    rows = sorted(lake_rows + kdb_rows, key=lambda r: _row_dt(r["date"]))
    if len(rows) > MAX_BARS:
        raise TicksRequestError(
            f"{len(rows)} {interval} bars is more than {MAX_BARS}: "
            "ask from a later start or for a wider interval")
    return {
        "symbol": symbol,
        "interval": interval,
        "bars": [{**r, "date": iso_utc(_row_dt(r["date"]))} for r in rows],
        "span": None if span is None else {"first": iso_utc(span[0]), "last": iso_utc(span[1])},
    }
