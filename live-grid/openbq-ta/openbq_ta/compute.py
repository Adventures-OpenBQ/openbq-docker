# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Evaluation in two passes.

Pass one materialises every distinct `Base` exactly once. Pass two evaluates
the indicator expressions, which reference those Bases by column name.

Doing this by hand rather than leaving it to Polars' optimiser is worth about
1.7x on a macro whose indicators share moving averages -- CSE captures 1.20x of
an available 2.06x (spec S3, D3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

from openbq_ta.exprs import Base
from openbq_ta.registry import Indicator, Req, StudyError, col_suffix, get
from openbq_ta.times import resolve_time


def collect_bases(reqs: list[Req]) -> dict[str, Base]:
    """Every Base the requests need, unique by key."""
    bases: dict[str, Base] = {}
    for req in reqs:
        for base in get(req.name).deps(req.params):
            bases[base.key] = base
    return bases


def session_columns(frame: pl.DataFrame, ind: Indicator, params: dict) -> dict[str, list]:
    """One value per session, held flat across every bar inside it.

    The frame is expected ASCENDING by date. Do NOT sort here: the returned
    lists are assigned onto the caller's frame by row position.
    shift() is what makes today read YESTERDAY's aggregates; without it every
    level is computed from the session it is drawn on, which is a lookahead.
    """
    every = str(params.get("anchor", "1d"))
    back = int(params.get("session_shift", 1))
    aggregates = ind.session_agg(params)
    sessions = (
        frame.group_by_dynamic("date", every=every, closed="left")
        .agg(**aggregates)
        .with_columns(**{name: pl.col(name).shift(back) for name in aggregates})
    )
    sessions = sessions.with_columns(ind.build(params, {}))
    missing = [name for name in ind.render if name not in sessions.columns]
    if missing:
        raise ValueError(f"{ind.name!r}: session build did not produce column(s) {missing} "
                         f"promised by render")
    outputs = list(ind.render)
    joined = frame.select("date").join_asof(
        sessions.select(["date", *outputs]), on="date", strategy="backward")
    return {name: joined[name].to_list() for name in outputs}


def resolve_times(req: Req, trades: Sequence = ()) -> dict[str, Any]:
    """`req.params` with each `times=` parameter resolved to a UTC datetime. A None stays
    None (avwap with no anchor runs from the first bar). Raises StudyError."""
    names = get(req.name).times
    if not names:
        return req.params
    return {**req.params, **{k: resolve_time(req.params[k], trades)
                             for k in names if req.params.get(k) is not None}}


# The bar columns a ticker study reads from the other ticker, renamed `<param>_<column>` (spec
# 2026-11-13 cross-symbol §1; adj_close too, because every such study reads adjusted close).
PRICE_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume")


def _has(n: int) -> str:
    return "has" if n == 1 else "have"


def _gaps(vs: str, symbol: str, frame: pl.DataFrame, other: pl.DataFrame) -> str | None:
    """The note for the dates one side lacks, counted over the union of both sides' dates."""
    mine, theirs = frame.select("date").unique(), other.select("date").unique()
    no_vs = mine.join(theirs, on="date", how="anti").height
    no_own = theirs.join(mine, on="date", how="anti").height
    total = mine.height + no_own
    clauses = []
    if no_vs:
        clauses.append(f"{no_vs} of {total} dates {_has(no_vs)} no {vs} bar")
    if no_own:
        head = f"{no_own}" if clauses else f"{no_own} of {total} dates"
        clauses.append(f"{head} {_has(no_own)} no {symbol or 'chart'} bar")
    return f"vs {vs}: {', '.join(clauses)}" if clauses else None


def _cross(frame: pl.DataFrame, req: Req, ind: Indicator, params: dict,
           others: dict[str, pl.DataFrame] | None, symbol: str) -> tuple[pl.DataFrame, str | None]:
    """A ticker study on the bars both tickers share, its columns left-joined back by date (a
    date either side lacks is null), and the gap note. Raises StudyError for what it cannot
    compute."""
    key = ind.tickers[0]
    vs = params.get(key)
    if vs is None or vs == "":
        raise StudyError(f"{ind.label} needs a second ticker")
    if req.units:
        raise StudyError("bd windows are not available on cross-symbol studies")
    other = (others or {}).get(vs)
    if other is None:
        raise StudyError(f"no bars for {vs}")
    theirs = other.select("date", *[pl.col(c).alias(f"{key}_{c}")
                                    for c in PRICE_COLUMNS if c in other.columns])
    shared = frame.join(theirs, on="date", how="inner", maintain_order="left")
    bases = {b.key: b for b in ind.deps(params)}
    if bases:
        shared = shared.with_columns([b.expr().alias(b.key) for b in bases.values()])
    suffix = col_suffix(req)
    built = shared.select("date", *[e.alias(e.meta.output_name() + suffix)
                                    for e in ind.build(params, bases)])
    return (frame.join(built, on="date", how="left", maintain_order="left"),
            _gaps(vs, symbol, frame, other))


def compute_with_bases(
    df: pl.DataFrame, reqs: list[Req], *, trades: Sequence = (), notes: list | None = None,
    others: dict[str, pl.DataFrame] | None = None, symbol: str = "",
) -> tuple[pl.DataFrame, dict[str, Base]]:
    """Evaluate `reqs` against `df`, keeping the intermediate Base columns.

    With `notes` a list, a study whose time does not resolve, or whose iterate/session_agg
    raises, is left out and `(req, message)` appended (spec 2026-11-04 §3); every other
    study computes. With `notes=None`, the error propagates.

    `others` maps a ticker to its bars, for a study that declares `tickers=`; `symbol` names
    the card's own ticker in that study's gap note.
    """
    if not reqs:
        return df, {}

    def drop(req: Req, exc: Exception) -> None:
        if notes is None:
            raise exc
        notes.append((req, str(exc)))

    work: list[tuple[Req, Indicator, dict]] = []
    for req in reqs:
        try:
            work.append((req, get(req.name), resolve_times(req, trades)))
        except StudyError as exc:
            drop(req, exc)
    cross = [w for w in work if w[1].tickers]   # computed last, each on its shared-bar frame
    work = [w for w in work if not w[1].tickers]
    bases: dict[str, Base] = {}
    for _, ind, params in work:
        for base in ind.deps(params):
            bases[base.key] = base
    frame = df
    if bases:
        frame = frame.with_columns([b.expr().alias(b.key) for b in bases.values()])

    seen: set[str] = set()
    exprs: list[pl.Expr] = []
    for req, ind, params in work:
        if ind.sessioned or ind.iterative:
            continue  # computed below, against the frame or the session frame
        suffix = col_suffix(req)
        for expr in ind.build(params, bases):
            name = expr.meta.output_name() + suffix
            if name in seen:
                continue  # the same indicator, same params, requested twice
            seen.add(name)
            exprs.append(expr.alias(name))
    if exprs:
        frame = frame.with_columns(exprs)

    # Path-dependent, then session-anchored studies: they read the frame rather than
    # contributing expressions to it.
    for req, ind, params in work:
        if not (ind.iterative or ind.sessioned):
            continue
        try:
            values = (ind.iterate(frame, params) if ind.iterative
                      else session_columns(frame, ind, params))
            missing = sorted(set(ind.render) - set(values))
            if missing:
                raise StudyError(f"{req.name!r} did not produce {missing}")
        except Exception as exc:  # noqa: BLE001 - one study's loop must not take the frame down
            drop(req, exc)
            continue
        suffix = col_suffix(req)
        for column, series in values.items():
            column += suffix
            if column not in frame.columns:
                frame = frame.with_columns(pl.Series(column, series, dtype=pl.Float64))
    for req, ind, params in cross:
        if all(c + col_suffix(req) in frame.columns for c in ind.render):
            continue  # the same study, same params, requested twice
        try:
            frame, gap = _cross(frame, req, ind, params, others, symbol)
        except Exception as exc:  # noqa: BLE001 - one study's join must not take the frame down
            drop(req, exc)
            continue
        if gap is not None and notes is not None:
            notes.append((req, gap))
    return frame, bases


def compute(df: pl.DataFrame, reqs: list[Req], *, trades: Sequence = (),
            notes: list | None = None, others: dict[str, pl.DataFrame] | None = None,
            symbol: str = "") -> pl.DataFrame:
    """Evaluate `reqs` against `df`. Base columns are an implementation detail."""
    frame, bases = compute_with_bases(df, reqs, trades=trades, notes=notes, others=others,
                                      symbol=symbol)
    return frame.drop([k for k in bases if k in frame.columns])
