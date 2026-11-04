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

import polars as pl

from openbq_ta.exprs import Base
from openbq_ta.registry import Indicator, Req, col_suffix, get


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


def compute_with_bases(
    df: pl.DataFrame, reqs: list[Req]
) -> tuple[pl.DataFrame, dict[str, Base]]:
    """Evaluate `reqs` against `df`, keeping the intermediate Base columns."""
    if not reqs:
        return df, {}
    bases = collect_bases(reqs)
    frame = df
    if bases:
        frame = frame.with_columns([b.expr().alias(b.key) for b in bases.values()])

    seen: set[str] = set()
    exprs: list[pl.Expr] = []
    for req in reqs:
        ind = get(req.name)
        if ind.sessioned or ind.iterative:
            continue  # computed below, against the frame or the session frame
        suffix = col_suffix(req)
        for expr in ind.build(req.params, bases):
            name = expr.meta.output_name() + suffix
            if name in seen:
                continue  # the same indicator, same params, requested twice
            seen.add(name)
            exprs.append(expr.alias(name))
    if exprs:
        frame = frame.with_columns(exprs)

    # Path-dependent, then session-anchored studies: they read the frame rather than
    # contributing expressions to it.
    for req in reqs:
        ind = get(req.name)
        if not (ind.iterative or ind.sessioned):
            continue
        values = (ind.iterate(frame, req.params) if ind.iterative
                  else session_columns(frame, ind, req.params))
        suffix = col_suffix(req)
        for column, series in values.items():
            column += suffix
            if column not in frame.columns:
                frame = frame.with_columns(pl.Series(column, series, dtype=pl.Float64))
    return frame, bases


def compute(df: pl.DataFrame, reqs: list[Req]) -> pl.DataFrame:
    """Evaluate `reqs` against `df`. Base columns are an implementation detail."""
    frame, bases = compute_with_bases(df, reqs)
    return frame.drop([k for k in bases if k in frame.columns])
