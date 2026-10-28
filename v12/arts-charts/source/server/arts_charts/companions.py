# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Art's Charts companion widgets (v12 part 5): ordinary data-only widgets beside the
arts_chart card, on BDOBB's backend widget protocol 0.1 with its interval amendment.

GET /charts/widgets.json is the manifest. GET /charts/widgets/bars lives in router()
(router.py), because it reads through that router's own fetch, the same as /series; the
manifest and the other companions are here. Every route is a read-only GET answering
{"rows": [...]}: none starts an acquisition, a fit or a push, and a refusal or an outage
fails the whole request rather than return part of it.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

import polars as pl
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from arts_charts.store import Store
from arts_charts.ta.session import is_intraday

#: Art's Charts' interval group, verbatim (client/src/lib/chart/chartGroups.ts CHART_INTERVAL),
#: so a companion joins the group an arts_chart card's Interval chip makes.
CHART_INTERVAL = "chart.interval"
#: The protocol's row ceiling. The latest rows are kept.
MAX_ROWS = 10_000
SESSIONS = ("extended", "regular")
#: The interval options the manifest offers (the wire set). Any width the provider serves is
#: accepted; one it does not is refused by router.refuse, as on /series.
INTERVALS = ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M")
#: The fixed study columns (ruling P7) and the engine column each one reads.
STUDIES = {"sma_20": "sma|period=20", "sma_50": "sma|period=50", "sma_200": "sma|period=200"}
INDICATORS = "sma:period=20,sma:period=50,sma:period=200"
BARS_KEYS = ("symbol", "interval", "session")
_TOKEN = re.compile(r"([1-9][0-9]{0,3})([smhdwM])")
#: Calendar days of history the bars widget reads, per unit: inside what the providers serve
#: intraday (yfinance: 1m about a week, up to 30m sixty days, 1h two years).
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


def _no_query(request: Request) -> None:
    try:
        query(request, ())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def window(interval: str, today: date) -> tuple[str, str]:
    """The bars widget's inclusive window at `interval`, ending today."""
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
    intraday = is_intraday(interval)
    rows = []
    for at, *values in kept.select(["date", *names]).iter_rows():
        time = at.strftime("%Y-%m-%dT%H:%M:%SZ") if intraday else at.date().isoformat()
        rows.append({"time": time, **dict(zip(["close", *STUDIES], values))})
    _check_order(rows, interval, intraday)
    return rows


MANIFEST: dict = {
    "arts_charts_bars": {
        "name": "Art's Charts bars and SMAs",
        "description": "Closes with their 20, 50 and 200-bar simple moving averages at the chosen"
                       " interval, from the Art's Charts server's own bars. Read-only.",
        "category": "Art's Charts",
        "type": "table",
        "endpoint": "/charts/widgets/bars",
        "gridData": {"w": 40, "h": 16},
        "params": [
            {"paramName": "symbol", "label": "Symbol", "type": "text", "value": "AAPL"},
            {"paramName": "interval", "label": "Interval", "value": "1d",
             "groupType": CHART_INTERVAL,
             "options": [{"label": i, "value": i} for i in INTERVALS]},
            {"paramName": "session", "label": "Session", "value": "extended",
             "options": [{"label": "Extended", "value": "extended"},
                         {"label": "Regular", "value": "regular"}]},
        ],
        "data": {"dataKey": "rows", "portfolio": {
            "protocol": "bdobb.portfolio/0.1", "view": "timeseries", "x": "time",
            "y": ["close", *STUDIES], "interval": "param"}},
    },
}


DOCUMENT_COLUMNS = [
    {"field": "id", "type": "string"}, {"field": "title", "type": "string"},
    {"field": "symbol", "type": "string"}, {"field": "interval", "type": "string"},
    {"field": "updated_at", "type": "date"}, {"field": "revision", "type": "number"},
]
MANIFEST["arts_charts_documents"] = {
    "name": "Art's Charts documents",
    "description": "Every saved chart on the Art's Charts server: title, symbol, interval, last"
                   " change and revision, newest first. Read-only.",
    "category": "Art's Charts",
    "type": "table",
    "endpoint": "/charts/widgets/documents",
    "gridData": {"w": 40, "h": 12},
    "params": [],
    "data": {"dataKey": "rows", "explorer": {
        "protocol": "bdobb.explorer/0.1", "dataset": "chart_documents", "snapshots": True,
        "columns": DOCUMENT_COLUMNS}},
}


def document_row(doc: dict) -> dict:
    return {"id": doc["id"], "title": doc["title"], "symbol": doc["symbol"],
            "interval": doc["interval"], "updated_at": doc["updated_at"],
            "revision": doc["revision"]}


WATCH_KIND = "watch_rule"
ALERT_COLUMNS = [
    {"field": "id", "type": "string"}, {"field": "kind", "type": "string"},
    {"field": "title", "type": "string"}, {"field": "symbol", "type": "string"},
    {"field": "created_at", "type": "date"}, {"field": "read", "type": "number"},
]
MANIFEST["arts_charts_alerts"] = {
    "name": "Art's Charts alerts",
    "description": "The inbox's items and the standing watches, newest first. kind watch_rule is"
                   " a watch; read is 1 once an item is read. Read-only: listing marks nothing.",
    "category": "Art's Charts",
    "type": "table",
    "endpoint": "/charts/widgets/alerts",
    "gridData": {"w": 40, "h": 12},
    "params": [],
    "data": {"dataKey": "rows", "explorer": {
        "protocol": "bdobb.explorer/0.1", "dataset": "chart_alerts", "snapshots": False,
        "columns": ALERT_COLUMNS}},
}


def alert_rows(store: Store) -> list[dict]:
    """Inbox items and watches as one list, newest first, capped at MAX_ROWS."""
    symbols = {doc["id"]: doc["symbol"] for doc in store.list()}
    items = [{"id": i["id"], "kind": i["kind"], "title": i["title"],
              "symbol": next((symbols[c] for c in i["chart_ids"] if c in symbols), ""),
              "created_at": i["created_at"], "read": 0 if i["read_at"] is None else 1}
             for i in store.list_inbox(MAX_ROWS)]
    watches = [{"id": w["id"], "kind": WATCH_KIND, "title": w["note"] or w["condition"],
                "symbol": symbols.get(w["chart_id"], ""), "created_at": w["created_at"],
                "read": 1}
               for w in store.list_watches()]
    rows = sorted(items + watches, key=lambda r: (r["created_at"], r["id"]), reverse=True)
    return rows[:MAX_ROWS]


def companions_router(store: Store) -> APIRouter:
    """The manifest and the read-only companions over `store`. Mounted before
    documents_router, whose /charts/{chart_id} would otherwise take `widgets.json`."""
    api = APIRouter()

    @api.get("/charts/widgets.json")
    def manifest(request: Request) -> JSONResponse:
        _no_query(request)
        return JSONResponse(MANIFEST)

    @api.get("/charts/widgets/documents")
    async def documents(request: Request):
        _no_query(request)
        docs = await asyncio.to_thread(store.list)
        return {"rows": [document_row(d) for d in docs[:MAX_ROWS]]}

    @api.get("/charts/widgets/alerts")
    async def alerts(request: Request):
        _no_query(request)
        return {"rows": await asyncio.to_thread(alert_rows, store)}

    return api
