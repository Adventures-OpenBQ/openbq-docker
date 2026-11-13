# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1

"""One builder, two routes.

`/ta_chart` and `/ta_chart_ws` both come through here. That is the reason the
live chart cannot disagree with the static one: there is no second
implementation to drift (spec D9).
"""

from __future__ import annotations

from datetime import datetime, timezone

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import polars as pl

from openbq_ta.compute import resolve_times
from openbq_ta.exprs import price_col
from arts_charts.ta.figure import build_ta_figure
from arts_charts.ta.macros import load_all
from arts_charts.ta.panes import Pane, all_reqs, assign
from openbq_ta.registry import Req, StudyError, get, resolve
from arts_charts.ta.session import is_intraday, running_session_start
from arts_charts.ta.sources import Annotation, LocalSource, columns_of


@dataclass(frozen=True)
class ChartParams:
    symbol: str = "AAPL"
    interval: str = "1d"
    source: str = "local"
    macro: str = "none"
    indicators: str = ""
    start: str | None = None
    end: str | None = None
    provider: str = "yfinance"
    basis: str = "adjusted"
    # "extended" (every bar) or "regular" (the feed's regular session only).
    # Only the literal "regular" filters; anything else is extended, with no
    # error -- the socket URL is built by a client that may be newer or older
    # than this server, and closing the stream on an unrecognised toggle is
    # worse than showing the whole tape. See arts_charts.ta.session.
    session: str = "extended"


#: Units a numeric parameter may wear on the wire. `bd` = business days: the
#: window counts SESSIONS rather than bars and is computed on the session
#: closes (arts_charts.ta.session.session_closes). A bare number is bars, as always.
_UNITS = ("bd",)


def _coerce(default: Any, raw: str) -> tuple:
    """The parameter's value, and the unit it wore -- `("50bd")` -> `(50, "bd")`.

    Stripped here rather than inside resolve() because a unit is grammar, not
    a parameter: any numeric parameter may wear one, and none of them may
    reach an indicator's build() as a string. An unrecognised suffix is left
    on and float() raises, which is what should happen -- `period=50bx` is a
    typo, and silently reading it as 50 bars draws the wrong line with no
    error anywhere.

    The registry's default says what the parameter IS: a numeric default is
    cast, an int default stays int, a float default stays float (so
    `bbands:k=2` is 2.0 and `stoch:k=14` is 14), and a text default -- an
    anchor, a session -- passes through. A name list would have to be edited
    for every study, and an operator's study (arts_charts.studies) edits no list.
    """
    if isinstance(default, bool) or not isinstance(default, (int, float)):
        return raw, None
    text = raw.strip()
    unit = next((u for u in _UNITS
                 if text.lower().endswith(u) and text[:-len(u)].strip()), None)
    if unit is not None:
        text = text[:-len(unit)].strip()
    value = float(text)
    return (int(value) if isinstance(default, int) and value.is_integer() else value), unit


def with_anchor(indicators: str, anchor: str | None) -> str:
    """Fold the widget's `anchor` param into the indicator list.

    A first-class param because Workspace's chart viewer has no click channel
    back to this backend -- anchoring by interaction lives in clients that own
    their renderer (bdobb-v2's real-time chart); here it is declarative. An
    avwap already present in `indicators` wins over the param.
    """
    anchor = (anchor or "").strip()
    if not anchor:
        return indicators
    chunks = (indicators or "").split(",")
    if any(chunk.strip().split(":")[0].strip() == "avwap" for chunk in chunks):
        return indicators
    spec = f"avwap:anchor={anchor}"
    return f"{spec},{indicators}" if indicators else spec


def parse_indicators(raw: str) -> list[Req]:
    """`"rsi:period=14,sma:period=200"` -> resolved requests."""
    reqs: list[Req] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, *fragments = chunk.split(":")
        # a value may itself contain colons (avwap:anchor=2026-08-28T14:30:00);
        # a fragment without "=" belongs to the previous pair's value
        pairs: list[str] = []
        for part in fragments:
            if "=" in part or not pairs:
                pairs.append(part)
            else:
                pairs[-1] += ":" + part
        params = {}
        units: dict[str, str] = {}
        defaults = get(name.strip()).params
        for pair in pairs:
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            key = key.strip()
            params[key], unit = _coerce(defaults.get(key), value.strip())
            if unit is not None:
                units[key] = unit
        # `source` rides in the same colon grammar but is NOT an indicator
        # parameter -- it is the request's own Local/EODHD routing choice. It
        # has to come out before resolve(), which raises on any key the
        # registry does not declare, and it is validated here rather than
        # defaulted: silently reading a typo as "local" would draw a line the
        # payload then labels as the vendor's.
        source = params.pop("source", None)
        if source is not None and source not in ("local", "eodhd"):
            raise ValueError(
                f"source must be 'local' or 'eodhd', got {source!r}")
        # `units` collides with resolve()'s own named argument the same way
        # `source` would -- reject it here instead of letting resolve() raise
        # a "multiple values for argument" TypeError that means nothing to
        # whoever reads the log.
        if "units" in params:
            raise ValueError("'units' is a reserved key, not an indicator parameter")
        reqs.append(resolve(name.strip(), source, units, **params))
    return reqs


def _naive_utc(value) -> datetime | None:
    """A bar's date as the naive-UTC datetime every indicator here reads.

    Bars arrive as bare dates (daily history), naive timestamps (kdb+ tick bars)
    and -- EODHD intraday over /series -- timestamps WITH an offset. The column
    used to be parsed by polars' `str.to_datetime()` with no time zone, which
    refuses a string that carries one: every study on the EODHD chart died in
    ta_series_ws (2026-09-20, "an SMA did not render"). Normalised here, one
    value at a time, so a column never has to agree on a single format. A value
    that is no date at all is null, as `strict=False` made it before.
    """
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else parsed.astimezone(timezone.utc).replace(tzinfo=None)


def bars_to_frame(bars: list[dict], basis: str = "adjusted") -> pl.DataFrame:
    """Bars from build_series into the frame the engine expects.

    Tick-derived bars have no adjusted close, so raw close stands in. That is
    correct rather than a fudge: intraday ticks are already unadjusted, and the
    alternative is a null column that silently voids every adjusted indicator.
    """
    # `basis` is a param like any other, and every other one in this engine
    # raises on an unknown value (resolve, price_col) rather than silently
    # falling back -- ?basis=raw is the only value besides "adjusted" that
    # means anything here, so reuse price_col's own check instead of letting
    # a typo (?basis=Raw) mean "adjusted" with no error anywhere.
    price_col(basis)
    schema = {"date": pl.Datetime, "open": pl.Float64, "high": pl.Float64,
              "low": pl.Float64, "close": pl.Float64, "adj_close": pl.Float64,
              "volume": pl.Float64, "vwap": pl.Float64}
    if not bars:
        return pl.DataFrame(schema=schema)
    rows = []
    for bar in bars:
        close = bar.get("close")
        # `.get(key, default)` fires only when the key is ABSENT. Providers
        # return an explicit null adjusted_close for instruments that have no
        # adjustment data -- indices, forex, crypto -- and that must fall back
        # too. Without this, all 13 price_basis="adjusted" indicators render
        # blank on those symbols, with no error anywhere to explain it.
        adjusted = bar.get("adjusted_close")
        rows.append({
            # NOT truncated to 10 chars: widgets.json offers 1h/5m/1m and kdb
            # tick bars carry a full timestamp, so a day's worth of intraday
            # bars would all plot at one x. /chart passes timestamps through
            # untouched; this route must not be the sibling that flattens them.
            "date": _naive_utc(bar.get("date")),
            "open": bar.get("open"), "high": bar.get("high"),
            "low": bar.get("low"), "close": close,
            # basis="raw" makes every price_basis="adjusted" indicator read
            # raw close, without touching a single indicator: they all read
            # the adj_close COLUMN, and this is where that column is decided.
            "adj_close": close if basis == "raw" or adjusted is None else adjusted,
            "volume": bar.get("volume") or 0.0,
            # Only tick-derived bars carry a true trade-weighted vwap; vendor
            # history has no per-trade data, so the column is null there.
            "vwap": bar.get("vwap"),
        })
    # history rows lead with vwap=None; without the override polars infers a
    # Null column and the first tick bar's float then fails to append
    return pl.DataFrame(rows, schema_overrides={"vwap": pl.Float64, "date": pl.Datetime("us")}).with_columns([
        pl.col(["open", "high", "low", "close", "adj_close", "volume", "vwap"])
          .cast(pl.Float64, strict=False),
    ])


def chart_subtitle(params: ChartParams) -> str:
    """The line shared by the figure title and the series payload.

    One spelling: `/ta_chart`'s figure and `/ta_series_ws`'s series payload
    used to copy this string independently, and `basis` was added on this
    branch to neither copy.
    """
    return f"{params.interval} · {params.source} · {params.basis}"


def vs_of(req: Req) -> str | None:
    """The other ticker a cross-symbol study reads -- its `tickers=` parameter's value -- or None
    (spec 2026-11-13 cross-symbol §3)."""
    keys = get(req.name).tickers
    value = req.params.get(keys[0]) if keys else None
    return None if value is None else str(value)


async def build_payload(
    params: ChartParams, frame: pl.DataFrame, eodhd_source=None,
    warmup: Callable[[Any, int], Awaitable[pl.DataFrame | None]] | None = None,
    others: dict[str, pl.DataFrame] | None = None, refused: dict[str, str] | None = None,
) -> tuple[dict, list[Pane], pl.DataFrame, list]:
    """The figure, its panes, the computed frame, and its annotations.

    Annotations come back rather than being folded into the title and dropped:
    the title only ships on a FIGURE push, so a caller that cannot see them
    change cannot know to send one (see main.ta_chart_ws).

    `others` are the bars of each `vs` ticker the server fetched; `refused` maps a `vs` it could not serve to the note its studies get instead (spec 2026-11-13 cross-symbol §3).
    """
    macro = None
    if params.macro and params.macro != "none":
        macros = load_all()
        if params.macro not in macros:
            raise KeyError(f"no such macro {params.macro!r}")
        macro = macros[params.macro]

    panes = assign(macro, parse_indicators(params.indicators))
    annotations: list = []

    # A time parameter is an ISO-8601 instant or OBS-n (spec 2026-11-04 §2). This server
    # holds no trade tape, so OBS-n never resolves here; either failure drops that one
    # study with an annotation, never the chart.
    reqs, notes = [], []
    for req in all_reqs(panes):
        vs = vs_of(req)
        if vs is not None and vs in (refused or {}):
            notes.append((req, (refused or {})[vs]))   # only this study is left off
            continue
        try:
            resolve_times(req)
            reqs.append(req)
        except StudyError as exc:
            notes.append((req, str(exc)))

    # The chart-wide `source` is now only a DEFAULT: each request may name its
    # own (v12.3.0 studies), so the split is per request rather than one
    # branch for the whole chart. Local runs first and the vendor joins onto
    # its frame, so one frame carries both and nothing downstream has to know
    # which engine produced which column.
    def effective(req: Req) -> str:
        return req.source or params.source

    vendor = [r for r in reqs if effective(r) == "eodhd"]
    local = [r for r in reqs if effective(r) != "eodhd"]
    # `warmup(first_bar, sessions)` (v12.4.5) fetches the daily bars before
    # the frame's first bar, for a `bd` window that reaches further back than
    # the chart does (see LocalSource.series). It is the
    # caller's -- this module computes and never fetches -- and it is
    # asked only when a request actually wears `bd` on an intraday chart.
    # `sessions` is the longest `bd` window any request asks for.
    sessions = max((int(r.params[k]) for r in reqs
                    for k, unit in r.units.items() if unit == "bd"), default=0)
    prior = None
    if warmup is not None and sessions and frame.height and is_intraday(params.interval):
        prior = await warmup(frame["date"][0], sessions)
    computed = frame
    if local:
        computed = LocalSource().series(
            computed, local, params.interval, params.symbol, prior, notes, others=others).frame
    if vendor and eodhd_source is not None:
        last_closed = str(frame["date"][-1]) if frame.height else ""
        # `prior` only when there is one: the vendor's signature is a contract
        # other sources (and every test double) already implement, and the
        # daily path -- the only one a vendor actually serves -- never has one.
        result = await eodhd_source.series(
            computed, vendor, params.symbol, params.interval, last_closed,
            **({} if prior is None else {"prior": prior}),
        )
        # Extend, not reassign -- a vendor request in the same chart must not
        # silently erase an annotation already collected.
        computed, annotations = result.frame, annotations + result.annotations
    elif vendor:
        # No vendor client configured: compute locally and say so, exactly as
        # an intraday request is answered.
        computed = LocalSource().series(
            computed, vendor, params.interval, params.symbol, prior, notes, others=others).frame
        annotations = annotations + [
            Annotation(col, "local", "no EODHD source configured")
            for r in vendor for col in columns_of(r)
        ]

    annotations = annotations + [Annotation(col, "local", msg)
                                 for req, msg in notes for col in columns_of(req)]
    figure = build_ta_figure(
        params.symbol, computed, panes, annotations, chart_subtitle(params)
    )
    return figure, panes, computed, annotations


def any_repaints(panes: list[Pane]) -> bool:
    """True when a pane holds an indicator whose history can change.

    Tail deltas assume causality: a revision to bar t changes bar t alone. That
    is false for ZigZag, whose pivots move well back into history when a new
    extreme arrives, so such a chart resends in full (spec D10).

    A `bd` (business-day) window breaks the same assumption -- a tick to the
    running session's close moves every bar of that session -- but it is NOT
    handled here, because the damage is bounded: those bars are the last
    session's, not the chart's. `delta_start` widens the delta to exactly
    them. Answering "repaints" instead resends the whole chart every push,
    forever, for the feature the spec asks the user to type.
    """
    from openbq_ta.registry import get

    return any(get(req.name).repaints for pane in panes for req in pane.reqs)


def revised_from(previous_dates: list[str], current_dates: list[str]) -> int:
    """The first row index whose value may have changed since the last push.

    The last bar of the previous push is always included: it was forming, so
    ticks since then have revised it.
    """
    if not previous_dates or len(current_dates) < len(previous_dates):
        return 0
    if current_dates[:len(previous_dates)] != previous_dates:
        return 0
    return max(0, len(previous_dates) - 1)


def delta_start(panes: list[Pane], previous_dates: list[str],
                current_dates: list[str], frame: pl.DataFrame,
                symbol: str = "") -> int:
    """`revised_from`, widened to the running session when a `bd` window asks.

    One function for both sockets rather than the same two lines in each: the
    Plotly loop and the series loop have to agree about which rows a delta
    covers, and the only way they cannot drift is to have no second copy.
    """
    start = revised_from(previous_dates, current_dates)
    # Any unit-bearing request computes on session closes, so its whole
    # running session moves with the close -- see running_session_start.
    if any(req.units for pane in panes for req in pane.reqs):
        start = min(start, running_session_start(frame, symbol))
    return start
