# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The five Art's Charts routes as one APIRouter over one bar source.

Ported from live-grid's app/main.py (openbb-docker @ c83446c0): the same
routes, query parameters, frames and close codes. The bar plumbing is one
ComposedBars (history per provider, the current session from live-grid when it
covers the symbol; composed.py), which also paces every fetch, and the EODHD
engine is gone: every study is computed locally in Polars over its bars.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx
import openbq_ta
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from arts_charts import studies
from arts_charts.catalog import catalog
from arts_charts.calendar import XNYS, ExchangeCalendar, UsEquitySessions
from arts_charts.classify import classify
from arts_charts.odp_bars import NotConfigured, Refused, check_interval
from arts_charts.ta.macros import load_all as load_macros_all
from arts_charts.ta.macros import to_wire as macro_to_wire
from arts_charts.ta.panes import all_reqs, assign
from arts_charts.ta.payload import (
    ChartParams, any_repaints, bars_to_frame, build_payload, chart_subtitle, delta_start,
    parse_indicators, with_anchor,
)
from openbq_ta.registry import REGISTRY, StudyError
from openbq_ta.studies import installed
from arts_charts.ta.series_payload import build_series_payload, series_delta
from arts_charts.ta.session import regular_only
from arts_charts.ta.warmup import pad_start, warmup_bars

if TYPE_CHECKING:  # composed.py reaches back here through conditions -> chart_body
    from arts_charts.composed import ComposedBars

log = logging.getLogger("arts_charts")

BarSource = Callable[[str, str, str, str], Awaitable[tuple[list[dict], dict]]]
#: The server default when a request names no provider (ARTS_CHARTS_DEFAULT_PROVIDER).
PROVIDER = "yfinance"
#: Every history provider a chart may name; one this server has no source for is a 422.
PROVIDERS = ("yfinance", "eodhd", "temporaldb")


def default_provider() -> str:
    """The provider of a chart that names none: ARTS_CHARTS_DEFAULT_PROVIDER, read per call."""
    return os.environ.get("ARTS_CHARTS_DEFAULT_PROVIDER", PROVIDER)

#: live-grid's /series failure body, key for key, so a client reads it unchanged.
ERROR_CACHE = {"cache": "error", "rows_from_cache": 0, "rows_from_upstream": 0,
               "rows_from_ticks": 0, "gaps_fetched": 0, "upstream_ms": 0.0, "kdb_ms": 0.0,
               "seam": None, "rows_from_vault": 0, "vault_days": [], "vault_fetched": [],
               "vault_refused": False}


def brief(exc: BaseException) -> str:
    """A client-safe account of a failure: httpx's own text embeds the upstream URL."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def close_reason(exc: BaseException) -> str:
    """A websocket close reason: the limit is 123 bytes, not characters."""
    return str(exc).encode("utf-8")[:123].decode("utf-8", errors="ignore")


def refuse(params: ChartParams) -> None:
    """Raise Refused for what this server cannot serve: another provider, an
    interval the provider does not list, or a study that asks for EODHD's engine."""
    if params.provider not in PROVIDERS:
        raise Refused(f"provider {params.provider!r} is not served; served: "
                      f"{', '.join(PROVIDERS)}")
    check_interval(params.interval, params.provider)
    macro = (load_macros_all().get(params.macro)
             if params.macro and params.macro != "none" else None)
    for req in all_reqs(assign(macro, parse_indicators(params.indicators))):
        if (req.source or params.source) == "eodhd":
            raise Refused(f"{req.name}: source=eodhd is not served; every study here is "
                          f"computed locally in Polars")


def session_seconds(sessions, symbol: str, day: str) -> float | None:
    """The regular session's length on `day`, in seconds, or None.

    What warmup.ts's padStart reads: the US session, and None -- "no
    calendar", padded as a 6.5h session -- for a symbol with no exchange
    calendar here (crypto, forex), or a calendar that cannot be read.
    """
    if classify(symbol) != "us":
        return None
    try:
        opened, closed = sessions.open_close(symbol, date.fromisoformat(day))
    except Exception as exc:  # noqa: BLE001 - a missing calendar pads generously, it does not fail
        log.warning("warm-up: no session hours for %s on %s (%s); assuming 6.5h", symbol, day, exc)
        return None
    return (closed - opened).total_seconds()


def router(bars: ComposedBars, calendar: ExchangeCalendar | None = None,
           default_provider: str = PROVIDER) -> APIRouter:
    """The five routes over `bars`; a request naming no provider gets `default_provider`.
    Custom studies load from TA_STUDIES_DIR now, before the catalog is projected,
    exactly as live-grid's create_app did."""
    api = APIRouter()
    studies.load_all()
    sessions = UsEquitySessions(classify, calendar)

    async def fetch(symbol: str, interval: str, start: str, end: str, provider: str,
                    session: str = "extended", fresh: bool = False):
        return await bars(symbol, interval, start, end, provider, session=session, fresh=fresh)

    def window(start: str | None, end: str | None) -> tuple[str, str]:
        today = date.today()
        return (start or str(today - timedelta(days=365)), end or str(today))

    def warmup_for(params: ChartParams):
        """The daily sessions before a chart, for a `bd` window (live-grid warmup_for).

        ponytail: a failed fetch is kept for the life of the closure, so an
        outage costs one call per socket rather than one per push.
        """
        memo: dict = {}

        async def _load(first, n_sessions: int):
            key = (first.date(), n_sessions)
            if key not in memo:
                try:
                    rows, _ = await fetch(
                        params.symbol, "1d",
                        str(first.date() - timedelta(days=n_sessions * 3 + 10)), str(first.date()),
                        params.provider)
                    memo[key] = bars_to_frame(rows, basis=params.basis)
                except Exception as exc:  # noqa: BLE001 - a missing warm-up must not kill the chart
                    log.warning("bd warm-up unavailable for %s: %s", params.symbol, exc)
                    memo[key] = None
            return memo[key]
        return _load

    async def series_state(params: ChartParams, warmup, answer):
        """One computation of a study chart over an answer already fetched:
        (panes, frame, annotations, meta, bars_error). `answer` is the bar
        source's (bars, meta) or the exception it raised; a failure degrades
        to no bars, as live-grid's socket always did. A bad macro or indicator
        RAISES (KeyError, ValueError) -- the socket closes on it, the snapshot
        answers 404/422."""
        if isinstance(answer, BaseException):
            log.warning("bars unavailable for %s: %s", params.symbol, answer)
            rows, meta, bars_error = [], {}, answer
        else:
            (rows, meta), bars_error = answer, None
        if params.session == "regular":
            rows = regular_only(rows, params.symbol, params.interval)
        _, panes, frame, annotations = await build_payload(
            params, bars_to_frame(rows, basis=params.basis),
            warmup=warmup,
        )
        return panes, frame, annotations, meta, bars_error

    async def auto_warmup(params: ChartParams, raw_start: str | None, s: str):
        """`warmup=auto`: (start, warmup_start, warmup_bars) -- live-grid's rule, verbatim."""
        if not raw_start:
            return s, None, 0
        if re.fullmatch(r"0+[smhdw]", params.interval):
            raise ValueError(f"interval {params.interval!r} has no length")
        macro = (load_macros_all().get(params.macro)
                 if params.macro and params.macro != "none" else None)
        reqs = all_reqs(assign(macro, parse_indicators(params.indicators)))
        n_bars = warmup_bars(
            [{"name": r.name, "params": r.params} for r in reqs],
            lambda name: list(REGISTRY[name].windows) if name in REGISTRY else None,
        )
        if calendar:
            await calendar.load_around(XNYS, datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc))
        seconds = await asyncio.to_thread(session_seconds, sessions, params.symbol, s[:10])
        padded = pad_start(s[:10], n_bars, params.interval, seconds)
        return padded, padded, n_bars

    @api.get("/ta_registry")
    async def ta_registry() -> JSONResponse:
        # eodhd: null on every entry -- there is no EODHD source behind this router,
        # so the client's advanced_chart_eodhd widget lists nothing. Projected per
        # request, so an installed study appears without a restart.
        return JSONResponse([{**entry, "eodhd": None} for entry in catalog()])

    @api.get("/health")
    async def health() -> dict:
        """Liveness, and the engine version (spec 2026-11-04 §3: verify_charts compares it
        with live-grid's)."""
        return {"status": "ok", "openbq_ta": openbq_ta.__version__}

    def studies_folder():
        """The studies folder, or 404 when managing studies is off (TA_STUDIES_API)."""
        directory = studies.studies_dir()
        if directory is None or not studies.api_enabled():
            raise HTTPException(404, "Not Found")
        return directory

    @api.get("/ta_studies")
    async def ta_studies() -> dict:
        studies_folder()
        return {"installed": installed()}

    @api.put("/ta_studies/{stem}")
    async def ta_studies_install(stem: str, request: Request) -> dict:
        directory = studies_folder()
        if stem == studies.PACK_STEM:
            raise HTTPException(409, "the Art's Charts pack is installed by the server itself")
        body = await request.body()
        if len(body) > 262_144:
            raise HTTPException(413, "a study file is at most 256 KiB")
        try:
            # In the event loop, not a thread: the registry is a plain dict that every
            # chart request reads.
            names = studies.install(directory, stem, body.decode("utf-8"))
        except (StudyError, UnicodeDecodeError) as exc:
            raise HTTPException(400, str(exc)) from None
        return {"stem": stem, "studies": names}

    @api.delete("/ta_studies/{stem}")
    async def ta_studies_remove(stem: str) -> dict:
        directory = studies_folder()
        if stem == studies.PACK_STEM:
            raise HTTPException(409, "the Art's Charts pack is installed by the server itself")
        names = studies.remove(directory, stem)
        if not names:
            raise HTTPException(404, f"no study file {stem!r} is installed")
        return {"removed": names}

    @api.get("/ta_macros")
    def ta_macros() -> JSONResponse:
        """Every chart macro, whole, read from disk per request (live-grid, verbatim)."""
        try:
            macros = load_macros_all()
        except Exception as exc:  # noqa: BLE001 - a bad macro must not blank the list
            log.warning("macro discovery failed: %s", exc)
            macros = {}
        wired = []
        for name, macro in sorted(macros.items()):
            try:
                wired.append(macro_to_wire(macro))
            except Exception as exc:  # noqa: BLE001 - one unserialisable macro must not 500 the list
                log.warning("skipping macro %s on /ta_macros: %s", name, type(exc).__name__)
        return JSONResponse(wired)

    @api.get("/series")
    async def series(symbol: str = "AAPL", interval: str = "1d", start: str | None = None,
                     end: str | None = None, provider: str | None = None,
                     session: str = "extended"):
        provider = provider or default_provider
        try:
            refuse(ChartParams(symbol=symbol, interval=interval, provider=provider))
            bars.check(provider, interval)
        except Refused as exc:
            raise HTTPException(400, str(exc)) from exc
        except NotConfigured as exc:
            raise HTTPException(422, str(exc)) from exc
        s, e = window(start, end)
        try:
            rows, meta = await fetch(symbol, interval, s, e, provider, session)
        except Exception as exc:  # noqa: BLE001
            log.warning("series failed for %s: %s", symbol, exc)
            return JSONResponse(
                {"symbol": symbol, "interval": interval, "start": s, "end": e, "bars": [],
                 "cache": {**ERROR_CACHE, "error": brief(exc)}},
                status_code=502,
            )
        return {"symbol": symbol, "interval": interval, "start": s, "end": e,
                "bars": rows, "cache": meta}

    @api.websocket("/ta_series_ws")
    async def ta_series_ws(ws: WebSocket) -> None:
        """The lightweight-charts client's study feed (live-grid, ported).

        The first frame is a full `series` push. With no tick source, nothing
        moves until the pacer refetches (once a bar), so only then is anything
        pushed again: a full push when a delta cannot carry the truth, a delta
        otherwise, by live-grid's own rule. `warmup=auto` moves `start` first.
        """
        await ws.accept()
        query = ws.query_params
        s, e = window(query.get("start"), query.get("end"))
        params = ChartParams(
            symbol=query.get("symbol", "AAPL"),
            interval=query.get("interval", "1d"),
            source=query.get("source", "local"),
            macro=query.get("macro", "none"),
            indicators=with_anchor(query.get("indicators", ""), query.get("anchor")),
            start=s, end=e, provider=query.get("provider") or default_provider,
            basis=query.get("basis", "adjusted"),
            session=query.get("session", "extended"),
        )
        warm: dict = {}
        try:
            refuse(params)
            bars.check(params.provider, params.interval)
            if query.get("warmup") == "auto":
                s, warm_start, warm_bars = await auto_warmup(params, query.get("start"), s)
                params = dataclasses.replace(params, start=s)
                warm = {"warmup_start": warm_start, "warmup_bars": warm_bars}
        except Exception as exc:  # noqa: BLE001 - a refusal is as permanent as a bad macro
            log.warning("ta_series_ws refused for %s: %s", params.symbol, exc)
            await ws.close(code=1011, reason=close_reason(exc))
            return
        interval_s = float(os.getenv("TA_PUSH_INTERVAL_MS", "1000")) / 1000.0
        warmup = warmup_for(params)
        previous: list[str] = []
        previous_marks: tuple[str, ...] = ()
        rev = 0
        answer: object = None
        try:
            while True:
                started = asyncio.get_running_loop().time()
                try:
                    fetched: object = await fetch(params.symbol, params.interval, s, e,
                                                  params.provider, params.session)
                except Exception as exc:  # noqa: BLE001 - a bars outage degrades, it does not end the stream
                    fetched = exc
                # The source hands back the SAME answer (or the same failure) until
                # something moved (composed.py): otherwise nothing is pushed.
                if fetched is not answer:
                    answer = fetched
                    try:
                        panes, frame, annotations, _, bars_error = await series_state(
                            params, warmup, answer)
                    except Exception as exc:  # noqa: BLE001 - bad macro/indicator: end the stream
                        log.warning("ta_series_ws failed for %s: %s", params.symbol, exc)
                        await ws.close(code=1011, reason=close_reason(exc))
                        return
                    subtitle = chart_subtitle(params)
                    if bars_error is not None:
                        subtitle += f"  ·  bars unavailable: {brief(bars_error)}"
                    dates = [str(d) for d in frame["date"].to_list()] if frame.height else []
                    marks = tuple(sorted({a.column for a in annotations}))
                    if (rev == 0 or any_repaints(panes) or bars_error is not None
                            or marks != previous_marks):
                        payload = build_series_payload(
                            frame, panes, params.symbol, subtitle, annotations, params.source)
                        await ws.send_json({"type": "series", "rev": rev, **payload, **warm})
                    else:
                        payload = series_delta(
                            frame, panes,
                            delta_start(panes, previous, dates, frame, params.symbol),
                            annotations, params.source,
                        )
                        await ws.send_json({"type": "delta", "rev": rev, **payload})
                    previous, previous_marks, rev = dates, marks, rev + 1
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(0.0, interval_s - elapsed))
        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("ta_series_ws ended for %s: %s", params.symbol, exc)
            return

    @api.get("/ta_snapshot")
    async def ta_snapshot(symbol: str = "AAPL", interval: str = "1d", source: str = "local",
                          macro: str = "none", indicators: str = "",
                          anchor: str | None = None, start: str | None = None,
                          end: str | None = None, provider: str | None = None,
                          basis: str = "adjusted", session: str = "extended",
                          warmup: str = "none", fresh: bool = False) -> JSONResponse:
        """`/ta_series_ws`'s first frame over plain HTTP, plus what it was built from.

        No "degrade and keep going": a refusal is a 400, an unknown macro or
        indicator a 404, a bad parameter a 422, and bars that cannot be had a
        502 that names no upstream detail. `fresh` skips the pacer's reused answer (the
        watch worker judges a completed bar, never a read made while it formed).
        """
        s, e = window(start, end)
        params = ChartParams(symbol, interval, source, macro, with_anchor(indicators, anchor),
                             s, e, provider or default_provider, basis, session)
        try:
            refuse(params)
            bars.check(params.provider, params.interval)  # NotConfigured: the 422 below
            warm_start, warm_bars = None, 0
            if warmup == "auto":
                s, warm_start, warm_bars = await auto_warmup(params, start, s)
                params = dataclasses.replace(params, start=s)
            try:
                answer: object = await fetch(symbol, interval, s, e, params.provider,
                                             params.session, fresh)
            except Exception as exc:  # noqa: BLE001 - becomes the 502 below, never the upstream text
                answer = exc
            panes, frame, annotations, meta, bars_error = await series_state(
                params, warmup_for(params), answer)
        except Refused as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if bars_error is not None:
            return JSONResponse({"detail": "bars unavailable"}, status_code=502)
        payload = build_series_payload(frame, panes, params.symbol, chart_subtitle(params),
                                       annotations, params.source)
        return JSONResponse({
            **payload,
            "annotations": [{"column": a.column, "source": a.source, "note": a.note}
                            for a in annotations],
            "chosen_provider": params.provider,
            "reason": "requested",
            # ponytail: every bar is called history, live-grid's included; meta.live says
            # whether the session is live. Mark bars by origin if a reader ever needs it.
            "bar_origin": ["history"] * frame.height,
            "meta": meta,
            "warmup_start": warm_start,
            "warmup_bars": warm_bars,
        })

    return api
