# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Watch conditions (spec §3): what `<series> <op> <value|series>` means on one chart.

A series is `close`, `high`, `low`, `volume`, or a study on the chart written as
its registry name with its parameters in registry order -- `rsi(14)`,
`bbands(20,2)`, `avwap(2026-09-01)` (the anchored VWAP) -- omitted trailing
parameters taking the registry's defaults. A study drawing several lines takes
an output after a dot, named as the served column is (`bbands(20,2).bb_up`);
without one it is the study's first line. Names are case-insensitive. Ops are
`>`, `<`, `crosses_above`, `crosses_below`.

A condition is checked against the chart when saved (resolve) and again at
every evaluation, because the chart can change under it. Values are read from a
/ta_snapshot payload -- the card's first /ta_series_ws frame -- so a watch sees
exactly the numbers the card draws. A missing value (warm-up, a dropped study)
never fires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from arts_charts.anchors import instant
from arts_charts.calendar import UsEquitySessions
from arts_charts.chart_body import SYMBOL_REF, indicators, study_groups, ticker_of
from arts_charts.classify import classify
from arts_charts.history_pacer import interval_step
from arts_charts.ta.panes import assign
from arts_charts.ta.payload import parse_indicators
from openbq_ta.registry import REGISTRY

OPS = ("crosses_above", "crosses_below", ">", "<")
PRICES = ("close", "high", "low", "volume")
MAX_LEN = 200
#: A served interval whose bars a watch can time. `5d` is yfinance's rolling
#: five-day bar, which has no fixed end to wait for.
WATCHABLE = ("1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "1w")
#: A bar counts as complete this long after it ends: the ODP refresh and clock skew.
SETTLE = timedelta(seconds=60)
#: Sessions with no calendar loaded: every weekday is a full session. The worker passes its own.
NO_CALENDAR = UsEquitySessions(classify)
_SPLIT = (re.compile(r"\s*(.+?)\s+(crosses_above|crosses_below)\s+(.+?)\s*"),
          re.compile(r"\s*([^<>]+?)\s*([<>])\s*([^<>]+?)\s*"))
_TERM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\(([^()]*)\))?(?:\.([A-Za-z_][A-Za-z0-9_]*))?")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_WINDOW = re.compile(r"\d+bd", re.I)


class ConditionError(ValueError):
    """Why a condition cannot be watched on this chart; the API answers it with 422."""


@dataclass(frozen=True)
class Term:
    text: str                 # as written: the key of its value in a firing's values
    name: str | None = None   # a price or a registry name; None for a number
    args: tuple[str, ...] = ()
    output: str | None = None
    number: float | None = None
    column: str | None = None  # after resolve: a price name or a served study column
    symbol: str | None = None  # a leading symbol as written (spec 2026-11-13 §3)
    ticker: str | None = None  # after resolve: the ticker it reads; None for a number


@dataclass(frozen=True)
class Condition:
    left: Term
    op: str
    right: Term


def _term(text: str) -> Term:
    if _NUMBER.fullmatch(text):
        return Term(text, number=float(text))
    m = _TERM.fullmatch(text)
    if m is None:
        raise ConditionError(f"{text!r} is not a series: close, high, low, volume or a study")
    name, args, output = m.group(1).lower(), m.group(2), m.group(3)
    parsed = tuple(a.strip() for a in args.split(",")) if args and args.strip() else ()
    return Term(text, name, parsed, output.lower() if output else None,
                column=name if name in PRICES else None)


def parse(text) -> Condition:
    """The condition's parts; ConditionError when it is not the grammar."""
    if not isinstance(text, str) or not 0 < len(text) <= MAX_LEN:
        raise ConditionError(f"a condition is 1-{MAX_LEN} characters")
    m = _SPLIT[0].fullmatch(text) or _SPLIT[1].fullmatch(text)
    if m is None:
        raise ConditionError("a condition is <series> <op> <value|series>, op one of "
                             "> < crosses_above crosses_below")
    left, op, right = _term(m.group(1)), m.group(2), _term(m.group(3))
    if left.number is not None:
        raise ConditionError("the left side is a series, not a number")
    return Condition(left, op, right)


def _columns(chunk: str) -> list[str]:
    return [s.column for pane in assign(None, parse_indicators(chunk)) for s in pane.series]


def _leading(arg: str) -> bool:
    """Whether a first argument can be a symbol (plan R1): the series-symbol rule, and not a
    number, a bd window or a time literal. The caller adds the text-parameter rule."""
    return (SYMBOL_REF.fullmatch(arg) is not None and _NUMBER.fullmatch(arg) is None
            and _WINDOW.fullmatch(arg) is None and instant(arg) is None and "@" not in arg)


def _ticker(term: Term, symbol: str | None, body: dict) -> str:
    if symbol is not None and symbol.startswith("$group:"):
        raise ConditionError(f"{term.text}: a symbol group is resolved by the dashboard; "
                             "a watch cannot name one")
    ticker, why = ticker_of(body, symbol)
    if ticker is None:
        raise ConditionError(f"{term.text}: {why}")
    return ticker


def _resolve(term: Term, body: dict, served: dict[str, set[str]]) -> Term:
    if term.number is not None:
        return term
    args, symbol = term.args, None
    if term.name in PRICES:
        if len(args) == 1 and term.output is None and _leading(args[0]):
            symbol, args = args[0], ()
        elif args or term.output or "(" in term.text:
            raise ConditionError(f"{term.text}: {term.name} takes no parameters or output")
        return replace(term, args=(), symbol=symbol, ticker=_ticker(term, symbol, body))
    entry = REGISTRY.get(term.name)
    if entry is None:
        raise ConditionError(f"{term.text}: no study {term.name!r}")
    names = list(entry.params)
    first_is_text = bool(names) and (entry.params[names[0]] is None
                                     or isinstance(entry.params[names[0]], str))
    if args and _leading(args[0]) and not (first_is_text and len(args) <= len(names)):
        symbol, args = args[0], args[1:]
    if len(args) > len(names):
        raise ConditionError(f"{term.text}: {term.name} takes at most {len(names)} parameter"
                             f"{'' if len(names) == 1 else 's'} ({', '.join(names)})")
    if any(not a or "=" in a for a in args):
        raise ConditionError(f"{term.text}: a parameter is a value, without '='")
    values = list(args)
    for key in entry.tickers:   # a cross-symbol study's vs is a series reference (cross-symbol §3)
        if key in names[:len(values)]:
            values[names.index(key)] = _ticker(term, values[names.index(key)], body)
    chunk = term.name + "".join(f":{k}={v}" for k, v in zip(names, values))
    try:
        columns = _columns(chunk)
    except (KeyError, ValueError) as exc:
        raise ConditionError(f"{term.text}: {exc.args[0] if exc.args else exc}") from None
    stems = [c.split("|")[0] for c in columns]
    if term.output is not None and term.output not in stems:
        raise ConditionError(f"{term.text}: no output {term.output!r}; outputs: {', '.join(stems)}")
    column = columns[stems.index(term.output) if term.output else 0]
    ticker = _ticker(term, symbol, body)
    if column not in served.get(ticker, set()):
        where = "" if symbol is None else f" for {symbol}"
        raise ConditionError(f"{term.text}: that study is not on this chart{where}")
    return Term(term.text, term.name, args, term.output, column=column, symbol=symbol,
                ticker=ticker)


def resolve(condition: Condition, body: dict) -> Condition:
    """The condition with every series bound to a ticker and a column it is served there."""
    if body.get("interval") not in WATCHABLE:
        raise ConditionError(f"a {body.get('interval')} chart cannot be watched; "
                             f"watchable: {', '.join(WATCHABLE)} (5d bars have no fixed end)")
    served = {ticker: set(_columns(indicators(studies)))
              for ticker, _, studies in study_groups(body)}
    return Condition(_resolve(condition.left, body, served), condition.op,
                     _resolve(condition.right, body, served))


def _value(term: Term, snapshot: dict, i: int, others: dict):
    if term.number is not None:
        return term.number
    if term.ticker in others:
        # Another ticker's side, read at the clock bar's time (plan R7): no bar there is a gap.
        at = snapshot["candles"][i]["time"]
        snapshot = others[term.ticker]
        i = next((j for j, c in enumerate(snapshot["candles"]) if c["time"] == at), None)
        if i is None:
            return None
    candle = snapshot["candles"][i]
    if term.column in PRICES:
        return candle.get(term.column)
    for pane in snapshot.get("panes", []):
        for series in pane.get("series", []):
            if series.get("column") == term.column:
                return next((p.get("value") for p in series.get("data", [])
                             if p.get("time") == candle["time"]), None)
    return None


def evaluate(condition: Condition, snapshot: dict, i: int, others: dict | None = None) -> dict:
    """{fired, values} for candle `i` of a /ta_snapshot payload (crosses read `i - 1` too).
    `others` holds the snapshots of the other tickers the condition names, by ticker."""
    others = others or {}
    left = _value(condition.left, snapshot, i, others)
    right = _value(condition.right, snapshot, i, others)
    values = {"bar_time": snapshot["candles"][i]["time"],
              condition.left.text: left, condition.right.text: right}
    if None in (left, right):
        return {"fired": False, "values": values}
    if condition.op == ">":
        return {"fired": left > right, "values": values}
    if condition.op == "<":
        return {"fired": left < right, "values": values}
    before = ((_value(condition.left, snapshot, i - 1, others),
             _value(condition.right, snapshot, i - 1, others))
              if i > 0 else (None, None))
    values["previous"] = {condition.left.text: before[0], condition.right.text: before[1]}
    if None in before:
        return {"fired": False, "values": values}
    if condition.op == "crosses_above":
        return {"fired": before[0] <= before[1] and left > right, "values": values}
    return {"fired": before[0] >= before[1] and left < right, "values": values}


def _naive_utc(at: datetime) -> datetime:
    return at.astimezone(timezone.utc).replace(tzinfo=None)


def bar_end(symbol: str, interval: str, start: datetime, sessions=NO_CALENDAR) -> datetime:
    """When the bar stamped `start` (naive UTC; a daily bar's date at 00:00) is over, naive UTC.

    A US symbol's day ends at the New York close (16:00, DST-aware, from the
    given sessions: holidays and early closes once the calendar is loaded); an intraday bar ends at its width or at the
    regular open, the close or the extended close, whichever comes first. A symbol with no
    exchange calendar runs by the UTC day.
    """
    zone = sessions.zone(symbol)
    if interval == "1d":
        return _naive_utc(sessions.open_close(symbol, start.date())[1])
    if interval == "1w":
        if zone == "UTC":
            return start + timedelta(days=7)
        friday = start.date() + timedelta(days=4 - start.weekday())
        while not sessions.is_open(symbol, friday):  # a holiday Friday: the week ends Thursday
            friday -= timedelta(days=1)
        return _naive_utc(sessions.open_close(symbol, friday)[1])
    if interval == "1M":  # a temporaldb month: to its last session's close
        last = (start.date().replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        while not sessions.is_open(symbol, last):
            last -= timedelta(days=1)
        return _naive_utc(sessions.open_close(symbol, last)[1])
    end = start + interval_step(interval)
    if zone != "UTC":
        day = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).date()
        regular = sessions.open_close(symbol, day)
        for edge in (regular[0], regular[1], sessions.extended_open_close(symbol, day)[1]):
            if start < _naive_utc(edge) < end:
                return _naive_utc(edge)
    return end


def complete_index(candles: list[dict], symbol: str, interval: str, now: datetime,
                   sessions=NO_CALENDAR) -> int | None:
    """The index of the latest candle complete at `now` (aware), or None.

    Only the last three candles are looked at: the bar being formed, the one
    just completed, and one more for a bar that is late to appear.
    """
    clock = _naive_utc(now)
    for i in range(len(candles) - 1, max(-1, len(candles) - 4), -1):
        start = datetime.fromisoformat(candles[i]["time"])
        if bar_end(symbol, interval, start, sessions) + SETTLE <= clock:
            return i
    return None
