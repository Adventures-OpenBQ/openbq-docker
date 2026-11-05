# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Art's Charts companion widgets (v12 part 5, trimmed by the 2026-11-04 engine split):
ordinary data-only widgets beside the arts_chart card, on BDOBB's backend widget protocol
0.1. GET /charts/widgets.json is the manifest; the documents and alerts companions are
here. The bars/SMA widget is live-grid's (S11). Every route is a read-only GET answering
{"rows": [...]}: none starts an acquisition, a fit or a push, and a refusal or an outage
fails the whole request rather than return part of it.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from arts_charts.store import Store

#: The protocol's row ceiling. The latest rows are kept.
MAX_ROWS = 10_000


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


MANIFEST: dict = {}


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
