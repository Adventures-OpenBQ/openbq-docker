# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The bars/SMA widget (spec 2026-11-04 §4, moved from Art's Charts' part 5 companion).

BDOBB backend widget protocol 0.1 with its interval amendment: a read-only GET answering
{"rows": [...]}, closes with their 20, 50 and 200-bar simple moving averages, at most
MAX_ROWS rows. A refusal or an outage fails the whole request; never partial rows.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import polars as pl
from fastapi import Request

#: Art's Charts' interval group, verbatim (client/src/lib/chart/chartGroups.ts CHART_INTERVAL),
#: so this widget joins the group an arts_chart card's Interval chip makes.
INTERVAL_GROUP = "chart.interval"
#: The protocol's row ceiling. The latest rows are kept.
MAX_ROWS = 10_000
INTERVALS = ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M")
#: The fixed study columns (part 5 ruling P7) and the engine column each one reads.
STUDIES = {"sma_20": "sma|period=20", "sma_50": "sma|period=50", "sma_200": "sma|period=200"}
INDICATORS = "sma:period=20,sma:period=50,sma:period=200"
KEYS = ("symbol", "interval")
_TOKEN = re.compile(r"([1-9][0-9]{0,3})([smhdwM])")
_INTRADAY = re.compile(r"\d+[smh]")
#: Calendar days of history per unit: inside what the providers serve intraday.
_WINDOW_DAYS = {"s": 6, "h": 700, "d": 3650, "w": 7300, "M": 18250}


def query(request: Request, allowed: tuple[str, ...]) -> dict[str, str]:
    """The request's query as a dict, refusing an undeclared or repeated key (protocol §10)."""
    pairs = request.query_params.multi_items()
    keys = [key for key, _ in pairs]
    unknown = sorted(set(keys) - set(allowed))
    if unknown:
        raise ValueError(f"unknown query parameter: {', '.join(unknown)}")
    if len(set(keys)) != len(keys):
        raise ValueError("a query parameter is repeated")
    return dict(pairs)


def window(interval: str, today: date) -> tuple[str, str]:
    """The widget's inclusive window at `interval`, ending today."""
    match = _TOKEN.fullmatch(interval)
    unit, n = (match.group(2), int(match.group(1))) if match else ("d", 1)
    days = (6 if n == 1 else 58) if unit == "m" else _WINDOW_DAYS[unit]
    return str(today - timedelta(days=days)), str(today)


def _seconds(interval: str) -> int:
    match = _TOKEN.fullmatch(interval)
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def _utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def _check_order(rows: list[dict], interval: str, intraday: bool) -> None:
    step = _seconds(interval) if intraday else 0
    for before, after in zip(rows, rows[1:]):
        if after["time"] <= before["time"]:
            raise ValueError(f"the {interval} bars are not ascending and unique at {after['time']}")
        if step and (_utc(after["time"]) - _utc(before["time"])).total_seconds() < step:
            raise ValueError(f"two {interval} bars are closer than {interval} at {after['time']}")


def bar_rows(frame: pl.DataFrame, interval: str) -> list[dict]:
    """One row per bar of the computed frame: `time`, `close` and the three SMAs.

    The leading bars whose 200-bar average is not yet defined are the warm-up and are left
    out. A bar after them without a date, a close or a study refuses the whole request, as
    does no complete bar at all; the host would otherwise get NaNs or a silent gap."""
    names = ["close", *STUDIES.values()]
    if frame.height == 0 or any(name not in frame.columns for name in names):
        raise ValueError(f"no {interval} bars to compute sma_200 from")
    ready = frame.select(pl.all_horizontal(
        [pl.col("date").is_not_null()]
        + [(pl.col(n).is_not_null() & pl.col(n).is_finite()).fill_null(False) for n in names]
    ).alias("ready"))["ready"].to_list()
    first = next((i for i, ok in enumerate(ready) if ok), None)
    if first is None:
        raise ValueError(f"not enough {interval} history for sma_200: it needs 200 bars")
    if not all(ready[first:]):
        raise ValueError(f"a {interval} bar after the warm-up has no close or study value")
    kept = frame.slice(first).tail(MAX_ROWS)
    intraday = _INTRADAY.fullmatch(interval) is not None
    rows = []
    for at, *values in kept.select(["date", *names]).iter_rows():
        time = at.strftime("%Y-%m-%dT%H:%M:%SZ") if intraday else at.date().isoformat()
        rows.append({"time": time, **dict(zip(["close", *STUDIES], values))})
    _check_order(rows, interval, intraday)
    return rows
