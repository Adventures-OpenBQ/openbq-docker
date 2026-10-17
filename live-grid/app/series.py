# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Joining tick-derived bars onto cached history.

The seam sits at the first bar boundary FULLY covered by ticks, not at the
first tick. A bar that ticks only partly cover would be missing its own opening
trades -- a wrong candle that looks entirely plausible on a chart -- so the
straddling bar comes from history and ticks own only what they cover whole.
"""

from datetime import datetime, timedelta, timezone

EPOCH = datetime(1970, 1, 1)


def window_end(end: str) -> datetime:
    """The last instant the requested window covers.

    Ticks are held for a rolling window that always ends *now*, so without
    clipping, a request for a window that closed months ago
    (`?start=2024-01-01&end=2024-06-01`) gets today's tick-derived bars
    appended to it -- a chart whose right edge is years past its own axis.

    A date-only `end` is INCLUSIVE of that whole day: the historical provider
    returns that day's bar, so treating it as midnight would drop the final
    day's ticks. An unparseable value clips nothing, which is exactly the
    behaviour that existed before this function.
    """
    text = str(end).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.max
    if len(text) == 10:  # YYYY-MM-DD -- a whole day, not its first instant
        return parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def seam_boundary(first_tick: datetime, interval: str) -> datetime:
    """The first bar boundary at or after `first_tick`."""
    from openbq_kdb.aggregate import bucket_ns

    width = timedelta(microseconds=bucket_ns(interval) / 1000)
    elapsed = first_tick - EPOCH
    buckets, remainder = divmod(elapsed, width)
    if remainder:
        buckets += 1
    return EPOCH + buckets * width


def tick_capable(interval: str, window: timedelta) -> bool:
    """True when a bar of this interval can be built from the tick window.

    Two ways to answer no, and both mean "serve this from history instead".
    The bucket may be wider than the ticks we hold, or the interval may not
    be a fixed number of nanoseconds at all -- `1mo` and `1w` are the real
    cases, and `bucket_ns` raises for them because `xbar` buckets on a
    constant width and a month is not one. Swallowing that ValueError is
    therefore correct, NOT a silent failure: the history path serves monthly
    bars perfectly well.

    It only looked like a bug while `bucket_ns` was a seven-entry table,
    because then it also swallowed `90m` -- an interval the ticks could have
    served -- and the provider answered the history request with daily bars
    and HTTP 200. Widening `bucket_ns` (2026-09-25) is what fixed that; this
    handler was never the right place for it.
    """
    from openbq_kdb.aggregate import bucket_ns

    try:
        width = timedelta(microseconds=bucket_ns(interval) / 1000)
    except ValueError:
        return False
    return width <= window


def _row_dt(value) -> datetime:
    """History rows carry the provider's ISO strings (passed through the
    response untouched, on purpose); tick rows carry datetimes. Compare as
    naive UTC datetimes without rewriting either on the wire: EODHD intraday
    strings end in `Z`, ticks never carry an offset."""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def stitch(history: list[dict], ticks: list[dict], boundary: datetime) -> list[dict]:
    """History strictly before `boundary`, then tick-derived bars, time-ordered."""
    if not ticks:
        return list(history)
    kept = [row for row in history if _row_dt(row["date"]) < boundary]
    if not kept:
        return sorted(ticks, key=lambda r: _row_dt(r["date"]))
    return sorted(kept + list(ticks), key=lambda r: _row_dt(r["date"]))
