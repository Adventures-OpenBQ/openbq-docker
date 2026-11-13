# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Operator-supplied studies: the @study decorator, the loader and the folder sync.

A built-in study is an `Indicator` record in openbq_ta.registry: metadata plus one Polars
function. `study` is that record as a decorator, so an operator writes the function and the
metadata and nothing else. Files live in one folder (`TA_STUDIES_DIR` in both services);
the service that manages them (Art's Charts) writes them, every service that runs them
reads them with `sync_dir` when a chart request or stream starts.

Importing a study file runs it: code execution inside the container, deliberately. The
folder is the operator's.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from collections.abc import Callable
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import polars as pl

from openbq_ta.compute import resolve_times
from openbq_ta.exprs import Base
from openbq_ta.registry import REGISTRY, Indicator, StudyError, get, register, resolve

log = logging.getLogger("openbq_ta.studies")

#: study name -> the file stem that registered it. Only a name in here may be
#: replaced or removed; a built-in is never shadowed by a file.
CUSTOM: dict[str, str] = {}

# The stem of the file being imported right now, so the decorator can record
# which file owns each study. A list rather than a str so a study file that
# imports another study file still attributes correctly.
_LOADING: list[str] = []

STEM = re.compile(r"[a-z][a-z0-9_]{0,63}")

#: What the chart can draw a line as (lightweight-charts' LineStyle) and fill
#: a band with (the app's own band primitive). Named here so a study file
#: that misspells one is refused at import, not drawn solid without a word.
PENS = ("solid", "dotted", "dashed", "large-dashed", "sparse-dotted")
PATTERNS = ("solid", "diagonal", "cross", "dots")


def study(
    *,
    name: str,
    label: str,
    params: dict,
    colors: dict[str, str | None],
    pane: str = "own",
    price_basis: str = "adjusted",
    group: str = "Custom",
    full: str = "",
    desc: str = "",
    description: str = "",
    wiki: str | None = None,
    windows: tuple[str, ...] = (),
    guides: tuple[float, ...] | list[float] = (),
    param_labels: dict[str, str] | None = None,
    param_steps: dict[str, float] | None = None,
    convention: str = "",
    deps: Callable[[dict], list[Base]] | None = None,
    pens: dict[str, str] | None = None,
    widths: dict[str, int] | None = None,
    shade: str | None = None,
    fill_opacity: float | None = None,
    fill_pattern: str = "solid",
    iterate: Callable[[pl.DataFrame, dict], dict[str, list]] | None = None,
    session_agg: Callable[[dict], dict] | None = None,
    times: tuple[str, ...] = (),
    tickers: tuple[str, ...] = (),
    render: dict[str, dict] | None = None,
) -> Callable:
    """Register a study.

    Vectorised (the default): decorate `fn(params) -> list[pl.Expr]`, one aliased expression
    per key of `colors`. With `session_agg=` the same function runs against one row per
    session (`session_agg(params)` names the aggregations), already shifted by
    `session_shift` (default 1), and its values are held flat across each session; an
    `anchor` parameter (default "1d") sets the session cadence.

    Iterative: pass `iterate=fn`, where `fn(frame, params) -> {column: values}` returns at
    least every key of `colors`; the study registers at once and `iterate` is returned, so
    the call is a statement rather than a decorator. A study gives either `iterate=` or a
    vectorised build, never both.

    `times` names the parameters that take a time: the engine resolves each (an ISO-8601
    instant or OBS-n, openbq_ta.times.resolve_time) and the study receives a UTC datetime.
    `render` adds per-output render keys over the default line (`{"h": {"type": "bar"}}`,
    `{"span": {"time_offset": 26}}`). `pens` is a line style per output (PENS), `widths` a
    line width per output, 1 to 4. A study whose outputs include a `_up` and a `_lo` is a
    band, and `shade`, `fill_opacity` and `fill_pattern` (PATTERNS) are its fill defaults.

    `tickers` names the one parameter that holds a second ticker; the engine computes the
    study on the bars both share, the other's as `vs_open` ... `vs_volume` (spec 2026-11-13
    cross-symbol §1).
    """
    if pane not in ("price", "own"):
        raise StudyError(f"{name!r}: pane must be 'price' or 'own', got {pane!r}")
    if not STEM.fullmatch(name):
        raise StudyError(f"{name!r}: a study name is lower-case letters, digits and _")
    if not colors:
        raise StudyError(f"{name!r}: colors must name at least one output column")
    if iterate is not None and session_agg is not None:
        raise StudyError(f"{name!r}: iterate= and session_agg= are two kinds of study; give one")
    if session_agg is not None and "anchor" not in params:
        params = {"anchor": "1d", **params}
    stray = sorted(set(windows) - set(params))
    if stray:
        raise StudyError(f"{name!r}: windows {stray} are not parameters")
    stray = sorted(set(times) - set(params))
    if stray:
        raise StudyError(f"{name!r}: times {stray} are not parameters")
    stray = sorted(set(tickers) - set(params))
    if stray:
        raise StudyError(f"{name!r}: tickers {stray} are not parameters")
    if len(tickers) > 1:
        raise StudyError(f"{name!r}: a study reads one other ticker; tickers names {list(tickers)}")
    if tickers and (iterate is not None or session_agg is not None):
        raise StudyError(f"{name!r}: a ticker study is vectorised; iterate= and session_agg= "
                         "cannot read a second ticker")
    render = dict(render or {})
    unknown = sorted(set(render) - set(colors))
    if unknown:
        raise StudyError(f"{name!r}: render names outputs {unknown} that colors do not")
    if name in REGISTRY and name not in CUSTOM:
        raise StudyError(f"{name!r} is a built-in study and cannot be replaced")
    pens = dict(pens or {})
    unknown = sorted(set(pens) - set(colors))
    if unknown:
        raise StudyError(f"{name!r}: pens name outputs {unknown} that colors do not")
    bad = sorted(v for v in pens.values() if v not in PENS)
    if bad:
        raise StudyError(f"{name!r}: pen {bad[0]!r} is not one of {list(PENS)}")
    widths = dict(widths or {})
    unknown = sorted(set(widths) - set(colors))
    if unknown:
        raise StudyError(f"{name!r}: widths name outputs {unknown} that colors do not")
    bad_width = [v for v in widths.values() if not isinstance(v, int) or not 1 <= v <= 4]
    if bad_width:
        raise StudyError(f"{name!r}: width {bad_width[0]!r} is not a whole number from 1 to 4")
    if fill_pattern not in PATTERNS:
        raise StudyError(f"{name!r}: fill_pattern {fill_pattern!r} is not one of {list(PATTERNS)}")
    if fill_opacity is not None and not 0 < fill_opacity <= 1:
        raise StudyError(f"{name!r}: fill_opacity must be in (0, 1], got {fill_opacity!r}")

    def add(build: Callable, doc: str | None) -> None:
        ind = Indicator(
            name=name, label=label, params=dict(params), pane=pane, price_basis=price_basis,
            convention=convention or (doc or "").strip() or f"Custom study {name}.",
            deps=deps or (lambda p: []),
            build=build,
            render={k: {"type": "line", "color": c,
                        **({"pen": pens[k]} if k in pens else {}),
                        **({"width": widths[k]} if k in widths else {}),
                        **render.get(k, {})}
                    for k, c in colors.items()},
            shade=shade, fill_opacity=fill_opacity, fill_pattern=fill_pattern,
            group=group, full=full, desc=desc, description=description, wiki=wiki,
            param_labels=dict(param_labels or {}), param_steps=dict(param_steps or {}),
            windows=tuple(windows), guides=list(guides),
            iterative=iterate is not None, iterate=iterate,
            sessioned=session_agg is not None, session_agg=session_agg, times=tuple(times),
            tickers=tuple(tickers),
        )
        REGISTRY.pop(name, None)
        register(ind)
        CUSTOM[name] = _LOADING[-1] if _LOADING else "<runtime>"

    if iterate is not None:
        add(lambda p, b: [], iterate.__doc__)
        return iterate

    def wrap(fn: Callable[[dict], list[pl.Expr]]) -> Callable:
        # Run once on the defaults so a missing or misnamed alias is refused at import, not
        # discovered as an empty line. Expressions are lazy; no frame is needed.
        produced = [e.meta.output_name() for e in fn(dict(params))]
        if sorted(produced) != sorted(colors):
            raise StudyError(
                f"{name!r}: build produces {sorted(produced)} but colors name {sorted(colors)}")
        add(lambda p, b: fn(p), fn.__doc__)
        return fn

    return wrap


def exprs_of(name: str, **params: Any) -> dict[str, pl.Expr]:
    """Another study's expressions, by output name, for nesting inside yours.

    `exprs_of("rsi", period=14)["rsi"]` is the RSI expression on the bar
    frame; alias it and build on it as on any Polars expression. Defaults
    come from the registry; unknown parameters raise as they would on the
    wire. A study whose expressions read shared sub-series (sma, bbands, atr)
    needs those materialised: declare `deps=lambda p: deps_of("sma", ...)`
    on your study, or the columns it reads will not exist. Iterative and
    sessioned studies (sar, pivots) compute outside the expression pass and
    cannot be nested.
    """
    ind = get(name)
    if ind.iterative or ind.sessioned:
        raise StudyError(f"{name!r} is not an expression study and cannot be nested")
    if ind.tickers:
        raise StudyError(f"{name!r} reads a second ticker and cannot be nested")
    req = resolve(name, **params)
    # The study's own Bases, so a build that reads them by key (sma, bbands)
    # composes; they are materialised only if your study declares them too.
    params = resolve_times(req)  # times= parameters arrive as UTC datetimes
    bases = {b.key: b for b in ind.deps(params)}
    return {e.meta.output_name(): e for e in ind.build(params, bases)}


def deps_of(name: str, **params: Any) -> list[Base]:
    """The shared sub-series another study reads, to declare as your own `deps`."""
    return get(name).deps(resolve_times(resolve(name, **params)))


def unload(stem: str) -> list[str]:
    """Forget every study `stem` registered. Returns their names."""
    names = [n for n, s in CUSTOM.items() if s == stem]
    for n in names:
        REGISTRY.pop(n, None)
        CUSTOM.pop(n, None)
    sys.modules.pop(f"ta_custom_{stem}", None)
    return names


def load_file(path: Path, stem: str | None = None) -> list[str]:
    """Import one study file. On any failure nothing it registered survives."""
    path = Path(path)
    stem = stem or path.stem
    if not STEM.fullmatch(stem):
        raise StudyError(f"{path.name}: a file name is lower-case letters, digits and _")
    # An explicit loader: spec_from_file_location infers one from the suffix
    # and returns None for install()'s `.upload` temp file.
    module_name = f"ta_custom_{stem}"
    spec = importlib.util.spec_from_file_location(
        module_name, path, loader=SourceFileLoader(module_name, str(path)))
    module = importlib.util.module_from_spec(spec)
    _LOADING.append(stem)
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit) as exc:  # a study file's exit() is a refusal, not ours
        unload(stem)
        raise StudyError(f"{path.name}: {type(exc).__name__}: {exc}") from exc
    finally:
        _LOADING.pop()
    sys.modules[spec.name] = module
    return [n for n, s in CUSTOM.items() if s == stem]


def load_dir(directory: Path | None) -> dict[str, list[str]]:
    """Every loadable study file in `directory`. A broken one is skipped, not
    fatal -- the proportion a macro folder applies: losing one
    file is the author's problem, losing every study is everyone's."""
    if directory is None or not Path(directory).is_dir():
        return {}
    loaded: dict[str, list[str]] = {}
    for path in sorted(Path(directory).glob("*.py")):
        try:
            loaded[path.stem] = load_file(path)
        except StudyError as exc:
            log.warning("skipping study %s: %s", path.name, exc)
    return loaded


def installed() -> dict[str, list[str]]:
    """File stem -> the study names it registered."""
    out: dict[str, list[str]] = {}
    for name, stem in CUSTOM.items():
        out.setdefault(stem, []).append(name)
    return out


#: stem -> st_mtime_ns of the file sync_dir last read (successfully or not).
_MTIMES: dict[str, int] = {}


def sync_dir(directory: Path | None) -> None:
    """Bring the registry in line with `directory`: load new files, reload changed ones,
    forget deleted ones. A file that fails is logged and skipped until it changes again;
    every other study keeps working. Called when a chart request or stream starts.

    Only `*.py` is read: an install stages `.{stem}.py.upload` and renames it into place,
    so a half-written file is never seen.
    """
    if directory is None or not Path(directory).is_dir():
        return
    seen: dict[str, int] = {}
    for p in Path(directory).glob("*.py"):
        try:
            seen[p.stem] = p.stat().st_mtime_ns
        except OSError as exc:  # dangling symlink, or deleted since the glob
            log.warning("skipping study %s: %s", p.name, exc)
    for stem in [s for s in _MTIMES if s not in seen]:
        unload(stem)
        del _MTIMES[stem]
    for stem, mtime in sorted(seen.items()):
        if _MTIMES.get(stem) == mtime:
            continue
        unload(stem)
        try:
            load_file(Path(directory) / f"{stem}.py")
        except StudyError as exc:
            log.warning("skipping study %s.py: %s", stem, exc)
        _MTIMES[stem] = mtime
