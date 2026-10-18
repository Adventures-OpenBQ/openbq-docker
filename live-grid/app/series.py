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


_MINUTE_NS = 60 * 10**9
_DAY_NS = 86_400 * 10**9
# EODHD intraday: one 1m request spans at most 120 days (5m: 600, ample for a chart).
ONE_MINUTE_SPAN_DAYS = 120


def history_source(interval: str) -> str | None:
    """The EODHD interval to fetch history at for this chart width, or None
    when only ticks can build it.

    A width is built only from a source that divides it evenly (user ruling
    "bar widths must divide evenly"): 15m, 30m and 1h come from 5m; 2m or 7m
    from 1m; anything under a minute from ticks alone. EODHD's own 1h is never
    used: it is stamped on the half hour, so it never meets the tick buckets
    at the seam. A day or more, or an interval that is not a fixed width
    (1w, 1mo), goes to the provider as it is, unchanged from before.
    """
    from openbq_kdb.aggregate import bucket_ns

    try:
        width = bucket_ns(interval)
    except ValueError:
        return interval
    if width % _DAY_NS == 0:
        return interval
    if width % (5 * _MINUTE_NS) == 0:
        return "5m"
    if width % _MINUTE_NS == 0:
        return "1m"
    return None


def one_minute_window(start: str, end: str) -> tuple[str, str]:
    """[start, end] clamped to the one 1m request EODHD accepts (120 days, both
    ends inclusive), keeping `end`. One request per call whatever `start` says:
    split into pieces, a window from 1900 was 386 sequential vendor calls from
    one URL (release review, 2026-10-18). A reversed or unparseable window is
    passed through for the provider to refuse."""
    from datetime import date

    try:
        lo, hi = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError:
        return start, end
    floor = hi - timedelta(days=ONE_MINUTE_SPAN_DAYS - 1)
    return (str(floor), end) if lo < floor else (start, end)


def resample(rows: list[dict], interval: str) -> list[dict]:
    """OHLCV bars of `interval` from finer history rows on the epoch clock grid
    (the tick buckets' grid). The caller guarantees the source width divides
    `interval`, so every source bar falls wholly inside one bucket. A bucket's
    vwap is the volume-weighted mean of its rows' vwaps when every traded row
    carries one, and absent otherwise (never estimated);
    other fields (adjusted_close) are not carried."""
    from openbq_kdb.aggregate import bucket_ns

    width = timedelta(microseconds=bucket_ns(interval) / 1000)
    buckets: dict[datetime, dict] = {}
    pv: dict[datetime, tuple[float, float]] = {}
    partial: set[datetime] = set()
    for row in sorted(rows, key=lambda r: _row_dt(r["date"])):
        t = _row_dt(row["date"])
        start = EPOCH + ((t - EPOCH) // width) * width
        bar = buckets.get(start)
        if row.get("volume"):
            if row.get("vwap") is None:
                partial.add(start)  # traded volume with no vwap: the bucket's vwap is unknown
            else:
                w, v = pv.get(start, (0.0, 0.0))
                pv[start] = (w + row["vwap"] * row["volume"], v + row["volume"])
        if bar is None:
            buckets[start] = {"date": start.isoformat() + "Z", "open": row["open"],
                              "high": row["high"], "low": row["low"], "close": row["close"],
                              "volume": row.get("volume")}
            continue
        bar["high"] = max(bar["high"], row["high"])
        bar["low"] = min(bar["low"], row["low"])
        bar["close"] = row["close"]
        if row.get("volume") is not None:
            bar["volume"] = (bar["volume"] or 0) + row["volume"]
    for start, (weighted, volume) in pv.items():
        if start not in partial:
            buckets[start]["vwap"] = weighted / volume
    return list(buckets.values())


def intraday(interval: str) -> bool:
    """True for a fixed width under a day."""
    from openbq_kdb.aggregate import bucket_ns

    try:
        return bucket_ns(interval) < _DAY_NS
    except ValueError:
        return False
