# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1

"""Operator-supplied studies.

A built-in study is an `Indicator` record in arts_charts.ta.registry: metadata plus
one Polars function. `study` below is that record as a decorator, so an
operator writes the function and the metadata and nothing else. The files
live in `TA_STUDIES_DIR`, loaded once at startup the way `TA_MACRO_DIR`
loads macros, or arrive through `POST /ta_studies` which writes into that
same directory -- the directory is the truth, the endpoint is a writer to it.

Importing a study file runs it. That is code execution inside this
container, deliberately: the directory is the operator's, and the endpoint
is off unless `TA_STUDIES_API` turns it on and is never reachable through
the public gateway (which forwards GET only). Behind the stack's HTTP Basic
credential, the same one every other route wears.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
from collections.abc import Callable
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import polars as pl

from arts_charts.ta.exprs import Base
from arts_charts.ta.registry import REGISTRY, Indicator, get, register, resolve

log = logging.getLogger("live-grid.ta")

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


class StudyError(ValueError):
    """A study file that cannot be trusted to register."""


def studies_dir() -> Path | None:
    raw = os.getenv("TA_STUDIES_DIR", "").strip()
    return Path(raw) if raw else None


def api_enabled() -> bool:
    return os.getenv("TA_STUDIES_API", "").strip().lower() in ("1", "true", "yes", "on")


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
) -> Callable:
    """Register the decorated function as a vectorised study.

    The function takes the resolved params and returns aliased Polars
    expressions, one per key of `colors`. `deps` names shared sub-series
    (arts_charts.ta.exprs.Base) the frame will carry under their `key` when the
    function runs. Iterative and sessioned studies are not covered here.

    `pens` is a line style per output (PENS; solid where unnamed) and
    `widths` a line width per output, 1 to 4 (1 where unnamed). A study
    whose outputs include a `_up` and a `_lo` is a band, and `shade`,
    `fill_opacity` and `fill_pattern` (PATTERNS) are the fill's defaults.
    """
    if pane not in ("price", "own"):
        raise StudyError(f"{name!r}: pane must be 'price' or 'own', got {pane!r}")
    if not STEM.fullmatch(name):
        raise StudyError(f"{name!r}: a study name is lower-case letters, digits and _")
    if not colors:
        raise StudyError(f"{name!r}: colors must name at least one output column")
    stray = sorted(set(windows) - set(params))
    if stray:
        raise StudyError(f"{name!r}: windows {stray} are not parameters")
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

    def wrap(fn: Callable[[dict], list[pl.Expr]]) -> Callable:
        # Run the function once on its defaults so a missing or misnamed alias
        # is refused at import, not discovered as an empty line on a chart.
        # Expressions are lazy; no frame is needed to read their output names.
        produced = [e.meta.output_name() for e in fn(dict(params))]
        if sorted(produced) != sorted(colors):
            raise StudyError(
                f"{name!r}: build produces {sorted(produced)} but colors name {sorted(colors)}"
            )
        ind = Indicator(
            name=name, label=label, params=dict(params), pane=pane,
            price_basis=price_basis,
            convention=convention or (fn.__doc__ or "").strip() or f"Custom study {name}.",
            deps=deps or (lambda p: []),
            build=lambda p, b: fn(p),
            render={k: {"type": "line", "color": c,
                        **({"pen": pens[k]} if k in pens else {}),
                        **({"width": widths[k]} if k in widths else {})}
                    for k, c in colors.items()},
            shade=shade, fill_opacity=fill_opacity, fill_pattern=fill_pattern,
            group=group, full=full, desc=desc, description=description, wiki=wiki,
            param_labels=dict(param_labels or {}), param_steps=dict(param_steps or {}),
            windows=tuple(windows), guides=list(guides),
        )
        REGISTRY.pop(name, None)
        register(ind)
        CUSTOM[name] = _LOADING[-1] if _LOADING else "<runtime>"
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
    req = resolve(name, **params)
    # The study's own Bases, so a build that reads them by key (sma, bbands)
    # composes; they are materialised only if your study declares them too.
    bases = {b.key: b for b in ind.deps(req.params)}
    return {e.meta.output_name(): e for e in ind.build(req.params, bases)}


def deps_of(name: str, **params: Any) -> list[Base]:
    """The shared sub-series another study reads, to declare as your own `deps`."""
    req = resolve(name, **params)
    return get(name).deps(req.params)


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
    except Exception as exc:
        unload(stem)
        raise StudyError(f"{path.name}: {type(exc).__name__}: {exc}") from exc
    finally:
        _LOADING.pop()
    sys.modules[spec.name] = module
    return [n for n, s in CUSTOM.items() if s == stem]


def load_dir(directory: Path | None) -> dict[str, list[str]]:
    """Every loadable study file in `directory`. A broken one is skipped, not
    fatal -- the same proportion arts_charts.ta.macros.load_macros applies: losing one
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


def install(directory: Path, stem: str, source: str) -> list[str]:
    """Write `source` as `<stem>.py` and load it, replacing that stem's studies.

    Loaded from a temp file first: a bad upload leaves the previous version
    of the file on disk and re-registers it, so a typo costs the sender a
    400 rather than costing the chart a study it had.
    """
    if not STEM.fullmatch(stem):
        raise StudyError("a study file name is lower-case letters, digits and _")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final, temp = directory / f"{stem}.py", directory / f".{stem}.py.upload"
    temp.write_text(source)
    unload(stem)
    try:
        names = load_file(temp, stem=stem)
    except StudyError:
        temp.unlink(missing_ok=True)
        if final.exists():
            load_file(final)
        raise
    temp.replace(final)
    return names


def remove(directory: Path, stem: str) -> list[str]:
    names = unload(stem)
    (Path(directory) / f"{stem}.py").unlink(missing_ok=True)
    return names
