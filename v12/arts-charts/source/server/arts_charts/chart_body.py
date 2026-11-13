# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""`chart/1`, the body of a chart document, and the check every save passes.

Field names are bdobb-v2's ChartCardState and the chart card's params. What
the server computes from is validated, and the instrument and the study
series are checked by `router.refuse` over the same indicator string
`/ta_series_ws` reads -- so a body that saves is a body the compute path
accepts, and the studies are checked against the one registry `/ta_registry`
lists. What only the card reads to reproduce itself -- `series` placement,
colour and style, `session`, `panels`, the display flags -- is checked for
shape, type and size and stored as written (S12, S13). `symbols` (spec 2026-11-13) is the
card's list when it has two or more tickers; `symbol` is always its first, and every server
reader keeps reading `symbol`.
"""
from __future__ import annotations

import math
import re

from arts_charts.anchors import instant, is_time_value
from arts_charts.odp_bars import Refused
from arts_charts.router import default_provider, refuse
from arts_charts.ta.payload import ChartParams
from openbq_ta.registry import REGISTRY

SCHEMA = "chart/1"
FLAGS = ("studyValues", "seriesPills", "snapshotHeader", "adjusted", "railHidden")
KEYS = {"schema", "symbol", "symbols", "provider", "interval", "range", "series", "session",
        "anchors", "levels", "drawings", "panels", *FLAGS}
ORIGINS = ("rita", "eodhd")
#: The drawing kinds and the geometry each records (bdobb-v2 ChartDrawing).
DRAWINGS = {"segment": {"a": "point", "b": "point"}, "ray": {"a": "point", "slope": "number"},
            "fib": {"a": "point", "b": "point"}, "gann": {"a": "point", "slopes": "slopes"}}


#: The card's series types (bdobb-v2 SeriesType) and the keys a series may carry; `expr`
#: is the client's (derived from these) and `source` is ignored everywhere, so neither is stored.
TYPES = ("candlestick", "ohlc", "line", "area", "volume", "performance", "study")
SERIES_KEYS = {"id", "type", "name", "params", "panel", "side", "color", "style", "symbol", "anchor"}
MAX_SERIES = 64
MAX_PANEL = 64
#: A card's symbol list holds one primary plus the four extra-bars slots (spec 2026-11-13 §1).
MAX_SYMBOLS = 5
#: What a series' `symbol` may hold (spec 2026-11-13 §1; mirrors client series.ts SYMBOL_REF):
#: `$ymbol`, `$group:<Name>`, `list:<n>`, or a ticker -- up to 64 characters with no comma, not
#: starting `$` or `list:`. The five bar types are held to it; a performance series is not.
SYMBOL_REF = re.compile(r"\$ymbol|\$group:.{1,64}|list:[1-9]\d{0,5}"
                        r"|(?![Ll][Ii][Ss][Tt]:)[^$,][^,]{0,63}")
SESSIONS = ("extended", "regular", "24hr")
#: A series' own colour, and a banded study's shade: `#RRGGBB` (bdobb-v2 Series.color).
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
#: The line styles and band hatches the card draws (client/src/lib/chart/pen.ts).
PENS = ("solid", "dotted", "dashed", "large-dashed", "sparse-dotted")
FILL_PATTERNS = ("solid", "diagonal", "cross", "dots")


class BodyError(ValueError):
    """Why a body is not a valid chart/1; the API answers it with 422."""


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonfinite(text: str) -> bool:
    try:
        return not math.isfinite(float(text))
    except ValueError:
        return False


def _text(x, limit: int) -> bool:
    return isinstance(x, str) and 0 < len(x) <= limit


def _list(body: dict, key: str) -> list:
    value = body.get(key, [])
    if not isinstance(value, list):
        raise BodyError(f"{key} must be a list")
    return value


def _point(where: str, p) -> None:
    if not (isinstance(p, dict) and set(p) == {"time", "value"}
            and _number(p["time"]) and _number(p["value"])):
        raise BodyError(f"{where} must be {{time, value}} with finite numbers")


def _drawing(i: int, d) -> None:
    where = f"drawings[{i}]"
    kind = d.get("kind") if isinstance(d, dict) else None
    shape = DRAWINGS.get(kind) if isinstance(kind, str) else None
    if shape is None:
        raise BodyError(f"{where}.kind must be one of {', '.join(DRAWINGS)}")
    if set(d) != {"kind", *shape}:
        raise BodyError(f"{where} ({d['kind']}) takes exactly {', '.join(['kind', *shape])}")
    for key, kind in shape.items():
        if kind == "point":
            _point(f"{where}.{key}", d[key])
        elif kind == "number" and not _number(d[key]):
            raise BodyError(f"{where}.{key} must be a finite number")
        elif kind == "slopes" and not (isinstance(d[key], list) and len(d[key]) == 3
                                       and all(_number(s) for s in d[key])):
            raise BodyError(f"{where}.{key} must be three finite numbers")


def _color(x) -> bool:
    return isinstance(x, str) and COLOR.fullmatch(x) is not None


#: Each key of a card series' `style` (bdobb-v2 Series.style) and the check its value passes.
STYLE = {
    "width": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4,
    "fill": lambda v: isinstance(v, bool),
    "fillOpacity": lambda v: _number(v) and 0 <= v <= 1,
    "shade": _color,
    "pen": lambda v: v in PENS,
    "fillPattern": lambda v: v in FILL_PATTERNS,
    "axisValue": lambda v: isinstance(v, bool),
    "outputs": lambda v: isinstance(v, list) and len(v) <= 16 and all(_text(o, 64) for o in v),
}


def _placed(i: int, s) -> None:
    """One series' placement and presentation: what the card needs to draw it
    where and how it was drawn, and nothing else."""
    where = f"series[{i}]"
    if not isinstance(s, dict):
        raise BodyError(f"{where} must be an object")
    unknown = sorted(set(s) - SERIES_KEYS)
    if unknown:
        raise BodyError(f"{where} has no key {unknown[0][:32]!r}")
    if s.get("type") not in TYPES:
        raise BodyError(f"{where}.type must be one of {', '.join(TYPES)}")
    if "id" in s and not _text(s["id"], 64):
        raise BodyError(f"{where}.id must be 1-64 characters")
    panel = s.get("panel")
    if not (isinstance(panel, int) and not isinstance(panel, bool) and 1 <= panel <= MAX_PANEL):
        raise BodyError(f"{where}.panel must be a panel number 1-{MAX_PANEL}")
    if s.get("side") not in ("left", "right"):
        raise BodyError(f"{where}.side must be left or right")
    if "color" in s and not _color(s["color"]):
        raise BodyError(f"{where}.color must be #RRGGBB")
    style = s.get("style", {})
    if not isinstance(style, dict):
        raise BodyError(f"{where}.style must be an object")
    for key, value in style.items():
        check = STYLE.get(key)
        if check is None:
            raise BodyError(f"{where}.style has no key {key[:32]!r}; it takes {', '.join(STYLE)}")
        if not check(value):
            raise BodyError(f"{where}.style.{key} is not a valid {key}")
    if (s["type"] == "study") != ("name" in s):
        raise BodyError(f"{where}: a study series, and only a study series, has a name")
    if s["type"] == "performance":
        if not is_time_value(s.get("anchor")) or ("symbol" in s and not _text(s["symbol"], 64)):
            raise BodyError(f"{where}: a performance series needs an anchor, and its symbol is text")
    elif "anchor" in s:
        raise BodyError(f"{where}: only a performance series has an anchor")
    if "symbol" in s:
        # A performance line keeps its pre-list rule (text, above), so one saved before lists
        # re-saves; client series.ts symbolAllowed makes the same split.
        if s["type"] != "performance" and (
                not isinstance(s["symbol"], str) or SYMBOL_REF.fullmatch(s["symbol"]) is None):
            raise BodyError(f"{where}.symbol must be a ticker, $ymbol, $group:<Name> or list:<n>")
    if s["type"] != "study" and s.get("params", {}) != {}:
        raise BodyError(f"{where}: only a study series has params")


def indicators(series: list) -> str:
    """The study series as the indicator string the compute path parses
    (`sma:period=20,rsi:period=14`), refusing what that grammar cannot carry."""
    chunks = []
    for i, s in enumerate(series):
        if s["type"] != "study":
            continue
        where = f"series[{i}]"
        name, params = s["name"], s.get("params", {})
        if not _text(name, 64) or any(c in name for c in ",:= "):
            raise BodyError(f"{where}.name must be a study name")
        times = REGISTRY[name].times if name in REGISTRY else ()
        if not isinstance(params, dict):
            raise BodyError(f"{where}.params must be an object")
        parts = [name]
        for key, value in params.items():
            if not _text(key, 64) or any(c in key for c in ",:= "):
                raise BodyError(f"{where}.params has a bad key {key!r}")
            if isinstance(value, dict):
                # S14: a time parameter is saved as {expr, at}; the server reads the instant.
                if key not in times or not is_time_value(value):
                    raise BodyError(f"{where}.params.{key} takes {{expr, at}} only as a time parameter")
                value = instant(value)
            if not (_number(value) or _text(value, 128)):
                raise BodyError(f"{where}.params.{key} must be a finite number or text")
            if isinstance(value, str) and any(c in value for c in ",="):
                raise BodyError(f"{where}.params.{key} may not contain ',' or '='")
            if isinstance(value, str) and _nonfinite(value):
                # The registry coerces text with float(), which reads "NaN" and "1e400".
                raise BodyError(f"{where}.params.{key} must be a finite number or text")
            parts.append(f"{key}={value}")
        chunks.append(":".join(parts))
    return ",".join(chunks)


def validate(body) -> None:
    """Raise BodyError naming the first thing wrong with `body`; return None when it is chart/1."""
    if not isinstance(body, dict):
        raise BodyError("body must be an object")
    unknown = sorted(set(body) - KEYS)
    if unknown:
        raise BodyError(f"unknown field {unknown[0]!r}")
    if body.get("schema") != SCHEMA:
        raise BodyError(f"schema must be {SCHEMA!r}")
    symbol = body.get("symbol")
    if not _text(symbol, 32) or symbol != symbol.strip():
        raise BodyError("symbol must be 1-32 characters with no surrounding space")
    if "symbols" in body:
        symbols = body["symbols"]
        if not (isinstance(symbols, list) and 2 <= len(symbols) <= MAX_SYMBOLS
                and all(_text(t, 32) and t == t.strip() and "," not in t for t in symbols)):
            raise BodyError(f"symbols must be 2-{MAX_SYMBOLS} tickers, each 1-32 characters "
                            "with no comma or surrounding space")
        if symbols[0] != symbol:
            raise BodyError("symbols[0] must equal symbol")
    for key in ("interval", "provider"):
        if key in body and not _text(body[key], 32):
            raise BodyError(f"{key} must be text")
    if "interval" not in body:
        raise BodyError("interval is required")
    series = _list(body, "series")
    if len(series) > MAX_SERIES:
        raise BodyError(f"series holds at most {MAX_SERIES}")
    for i, s in enumerate(series):
        _placed(i, s)
    try:
        refuse(ChartParams(symbol=symbol, interval=body["interval"],
                           provider=body.get("provider", default_provider()),
                           indicators=indicators(series)))
    except Refused as exc:
        raise BodyError(str(exc)) from None
    except (KeyError, ValueError) as exc:  # the registry's verdict on a study
        raise BodyError(f"series: {exc.args[0] if exc.args else exc}") from None
    if "session" in body and body["session"] not in SESSIONS:
        raise BodyError(f"session must be one of {', '.join(SESSIONS)}")
    if "range" in body:
        r = body["range"]
        if not (isinstance(r, dict) and set(r) == {"from", "to"}
                and is_time_value(r["from"]) and is_time_value(r["to"])):
            raise BodyError("range must be {from, to}, each an ISO-8601 instant, OBS-n or {expr, at}")
    for i, a in enumerate(_list(body, "anchors")):
        if not is_time_value(a):
            raise BodyError(f"anchors[{i}] must be an ISO-8601 instant, OBS-n or {{expr, at}}; "
                            f"the host resolves expressions")
    for i, level in enumerate(_list(body, "levels")):
        if not (isinstance(level, dict) and set(level) <= {"price", "origin"}
                and _number(level.get("price"))
                and level.get("origin", ORIGINS[0]) in ORIGINS):
            raise BodyError(f"levels[{i}] must be {{price, origin?}} with origin rita or eodhd")
    for i, d in enumerate(_list(body, "drawings")):
        _drawing(i, d)
    if "panels" in body and not isinstance(body["panels"], str):
        raise BodyError("panels must be text")
    for flag in FLAGS:
        if flag in body and not isinstance(body[flag], bool):
            raise BodyError(f"{flag} must be true or false")


def unresolved(body: dict) -> list[str]:
    """Each stored time with no instant the server can read (S14: a legacy entry holding
    only an expression), named for a note. The host fills its instant in on the document's
    next save; until then that one entry is skipped and the rest of the chart draws."""
    out = [f"range.{end} {body['range'][end]!r}" for end in ("from", "to")
           if "range" in body and instant(body["range"][end]) is None]
    out += [f"anchors[{i}] {a!r}" for i, a in enumerate(body.get("anchors", [])) if instant(a) is None]
    for i, s in enumerate(body.get("series", [])):
        if s["type"] == "performance" and instant(s.get("anchor")) is None:
            out.append(f"series[{i}] performance anchor {s.get('anchor')!r}")
        times = REGISTRY[s["name"]].times if s["type"] == "study" and s.get("name") in REGISTRY else ()
        for key in times:
            value = s.get("params", {}).get(key)
            if value is not None and instant(value) is None:
                out.append(f"series[{i}] {s['name']} {key} {value!r}")
    return out


def ticker_of(body: dict, ref: str | None) -> tuple[str | None, str | None]:
    """The ticker a series `symbol` names on this document (spec 2026-11-13 §2), or None and why.
    Absent, `$ymbol` and `list:1` are the list's first entry; a literal is upper-cased. A symbol
    group is the dashboard's, so the server names it rather than resolving it."""
    symbols = body.get("symbols") or [body["symbol"]]
    if ref is None or ref == "$ymbol":
        return symbols[0], None
    if ref.startswith("list:"):
        n = int(ref[len("list:"):])
        if n <= len(symbols):
            return symbols[n - 1], None
        entries = "entry" if len(symbols) == 1 else "entries"
        return None, f"list has {len(symbols)} {entries}, no {ref}"
    if ref.startswith("$group:"):
        return None, "a symbol group is resolved by the dashboard, not by the server"
    return ref.upper(), None


def _label(ticker: str, ref: str | None) -> str:
    return f"{ticker} ({ref})" if ref is not None and ref.startswith("list:") else ticker


def series_tickers(body: dict) -> tuple[list[str | None], list[str]]:
    """Each series' ticker as its card resolves it -- `MSFT (list:2)` for a list position --
    or None, with a note naming why (ticker_of)."""
    tickers: list[str | None] = []
    notes: list[str] = []
    for i, s in enumerate(body.get("series", [])):
        ref = s.get("symbol")
        ticker, why = ticker_of(body, ref)
        tickers.append(None if ticker is None else _label(ticker, ref))
        if ticker is None:
            notes.append(f"series[{i}] {ref}: {why}")
    return tickers, notes


def study_groups(body: dict) -> list[tuple[str, str, list[dict]]]:
    """(ticker, label, studies) per ticker a study draws on -- the card's study sockets
    (spec 2026-11-13 §2-3). list:1 is first and always present, with or without studies; a
    study whose reference does not resolve is in none (series_tickers notes it)."""
    first = (body.get("symbols") or [body["symbol"]])[0]
    groups: dict[str, tuple[str, list[dict]]] = {first: (first, [])}
    for s in body.get("series", []):
        if s["type"] != "study":
            continue
        ticker, _ = ticker_of(body, s.get("symbol"))
        if ticker is not None:
            groups.setdefault(ticker, (_label(ticker, s.get("symbol")), []))[1].append(s)
    return [(ticker, label, studies) for ticker, (label, studies) in groups.items()]


def with_defaults(body: dict) -> dict:
    """A validated `body` with every study's missing params filled from the registry (P3),
    so no stored study has `params: {}` (but avwap, whose only default is None); explicit params are kept. Returns a copy."""
    out = {**body}
    if "series" in body:
        out["series"] = [
            {**s, "params": {**{k: v for k, v in REGISTRY[s["name"]].params.items() if v is not None},
                             **s.get("params", {})}} if s["type"] == "study" else s
            for s in body["series"]]
    return out
