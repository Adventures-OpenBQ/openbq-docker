# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1

"""The local engine: Polars compute over the bars already in hand.

live-grid carried a second, EODHD, engine behind the same shape; it does not
come over (arts-charts-openbq spec, R8/R9). `build_payload` still accepts an
`eodhd_source` -- any vendor with that contract -- but the router never
passes one, and refuses `source=eodhd` before it would matter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import polars as pl

from arts_charts.classify import classify
from arts_charts.ta.compute import compute
from arts_charts.ta.registry import Req, col_suffix, get
from arts_charts.ta.session import (
    SESSION_DATE,
    is_intraday,
    session_closes,
    session_date,
)

log = logging.getLogger("live-grid.ta")


@dataclass(frozen=True)
class Annotation:
    """Why a series is not what the chosen source would have given."""

    column: str
    source: str
    note: str


@dataclass
class Result:
    frame: pl.DataFrame
    annotations: list[Annotation] = field(default_factory=list)
    calls: int = 0


def columns_of(req: Req) -> list[str]:
    """The frame columns this request produces, suffixed per its parameters."""
    suffix = col_suffix(req)
    return [c + suffix for c in get(req.name).render]


def _is_bd(req: Req) -> bool:
    """True when any of this request's windows counts business days."""
    return "bd" in req.units.values()


class LocalSource:
    """Polars compute over the bars already in hand."""

    name = "local"

    def series(self, df: pl.DataFrame, reqs: list[Req],
               interval: str = "1d", symbol: str = "",
               prior: pl.DataFrame | None = None) -> Result:
        """`interval`, `symbol` and `prior` are read only by `bd` windows.

        `prior` (v12.4.5) is a DAILY frame of the sessions before the first
        bar of `df`. A `bd` window used to see only the sessions inside the
        chart's own window, so `SMA(50bd)` on a 5D chart had five closes to
        average and drew nothing at all. The warm-up is daily bars rather
        than a wider intraday fetch because fifty sessions of 1m bars is
        ~50,000 rows fetched to keep fifty numbers.

        ponytail: a prior session's close is the vendor's official daily
        close, while a session inside the window closes on its last bar --
        on an Extended chart that is the 20:00 print, not the 16:00 one.
        The two differ by after-hours drift on the warm-up rows only.
        Upgrade path: warm up from intraday bars when that drift matters.

        A `bd` window counts sessions: it is computed on one row per session
        (`session_closes`) and then broadcast back onto every bar of its
        session, so `SMA(50bd)` on a 1m chart is fifty DAYS of closes rather
        than fifty minutes. The join is by session date and not by time, or
        every bar before the session's last would read yesterday's value.

        On a daily-or-coarser frame a bar IS a session, so `50bd` is 50 bars
        and the ordinary path is already the right answer -- the defaults say
        so, which keeps every existing caller (and the parity tests) intact.

        ponytail: that is only literally true on `1d`. `is_intraday` treats
        `1wk`/`1mo` as "not intraday" too, so `50bd` there silently falls
        through to the ordinary path and means 50 bars -- 50 weeks or months,
        not 50 sessions. Upgrade path: reject a `bd` unit when the interval is
        coarser than `1d`, once a caller actually asks for one.
        """
        bd = [r for r in reqs if _is_bd(r)]
        if not bd or df.height == 0 or not is_intraday(interval):
            return Result(compute(df, reqs))
        feed = classify(symbol)
        wanted = [c for r in bd for c in columns_of(r)]
        # Two frames, one per clock: the bar frame for ordinary requests, the
        # session frame for the bd ones. Their Base columns never meet, which
        # is what keeps `period=50` and `period=50bd` honest.
        closes = session_closes(df, feed)
        if prior is not None and prior.height:
            # A daily bar is stamped at midnight, so its date IS its session
            # -- session_date() would read 00:00 UTC as the evening before in
            # New York. Strictly before the window's first session: the fetch
            # that produced `prior` may end on that same day.
            before = prior.with_columns(
                pl.col("date").cast(pl.Datetime).dt.date().alias(SESSION_DATE)
            ).filter(pl.col(SESSION_DATE) < closes[SESSION_DATE][0])
            closes = pl.concat(
                [before.select([c for c in closes.columns if c in before.columns]),
                 closes], how="diagonal_relaxed")
        sessions = compute(closes, bd)
        frame = compute(df, [r for r in reqs if not _is_bd(r)])
        joined = (
            frame.with_columns(session_date(feed))
            .join_asof(sessions.select([SESSION_DATE, *wanted]),
                       on=SESSION_DATE, strategy="backward")
            .drop(SESSION_DATE)
        )
        return Result(joined)
