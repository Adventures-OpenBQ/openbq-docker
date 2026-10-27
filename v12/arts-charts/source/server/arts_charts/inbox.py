# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The inbox (spec §4) over HTTP.

`GET /inbox`, `GET /inbox/{id}`, `GET /inbox/{id}/snapshots/{n}.png`,
`POST /inbox/{id}/read`, `DELETE /inbox/{id}` for the user; `POST /inbox` for
the worker alone, with a worker token in `X-Arts-Charts-Worker`. The worker
names the charts to picture and this app renders them, so a snapshot is the
document as it is once Rita has annotated it. Every change is announced on
/charts/events as `{kind: "inbox", id, revision: 0, by}`.

An item's title and body are Rita's or the worker's text: untrusted markdown
to whoever shows it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from arts_charts.documents import Feed
from arts_charts.snapshots import SnapshotError
from arts_charts.store import NotFound, Store, is_chart_id
from arts_charts.tokens import TokenError, verify

KINDS = ("watch", "schedule", "system")
MAX_TITLE = 200
MAX_BODY = 20_000
MAX_CHARTS = 16
WORKER_HEADER = "x-arts-charts-worker"
#: GET /inbox returns at most this many items; with no `limit` it returns this many.
MAX_PAGE = 200
#: A chart's PNG, or SnapshotError (Snapshots.render's, without its metadata).
Render = Callable[[str], Awaitable[bytes]]


def _cursor(item: dict) -> str:
    """The opaque cursor that resumes the listing after `item`."""
    raw = json.dumps([item["created_at"], item["id"]]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(cursor: str) -> tuple[str, str]:
    try:
        created_at, item_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError):
        raise HTTPException(422, "before is a cursor from a previous page") from None
    if not (isinstance(created_at, str) and isinstance(item_id, str)):
        raise HTTPException(422, "before is a cursor from a previous page")
    return created_at, item_id


def _item(data) -> dict:
    """The worker's `{kind, title, body, chart_ids, snapshots}`, checked."""
    keys = {"kind", "title", "body", "chart_ids", "snapshots"}
    if not isinstance(data, dict) or set(data) != keys:
        raise HTTPException(422, f"an inbox item is exactly {', '.join(sorted(keys))}")
    if data["kind"] not in KINDS:
        raise HTTPException(422, f"kind is one of {', '.join(KINDS)}")
    for key, limit in (("title", MAX_TITLE), ("body", MAX_BODY)):
        if not isinstance(data[key], str) or len(data[key]) > limit:
            raise HTTPException(422, f"{key} is text of at most {limit} characters")
    for key in ("chart_ids", "snapshots"):
        ids = data[key]
        if not (isinstance(ids, list) and len(ids) <= MAX_CHARTS
                and all(isinstance(i, str) and is_chart_id(i) for i in ids)):
            raise HTTPException(422, f"{key} is a list of at most {MAX_CHARTS} chart ids")
    return data


def inbox_router(store: Store, feed: Feed, render: Render) -> APIRouter:
    api = APIRouter()

    async def call(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except NotFound:
            raise HTTPException(404, "no such inbox item") from None

    def item_id_of(item_id: str) -> str:
        if not is_chart_id(item_id):  # a uuid, as add_inbox mints
            raise HTTPException(404, "no such inbox item")
        return item_id

    def announce(item_id: str, by: str) -> None:
        feed.publish({"kind": "inbox", "id": item_id, "revision": 0, "by": by})

    @api.get("/inbox")
    async def list_inbox(before: str | None = None, limit: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE)):
        """A page, newest first: `next` is the `before` of the following page, null on the
        last. `unread` counts the whole table, not the page."""
        after = None if before is None else _after(before)
        items = await call(store.list_inbox, limit + 1, after)
        more = len(items) > limit
        items = items[:limit]
        return {"items": items, "unread": await call(store.unread_inbox),
                "next": _cursor(items[-1]) if more else None}

    @api.post("/inbox", status_code=201)
    async def add_item(request: Request):
        try:
            verify(os.environ.get("ARTS_CHARTS_SECRET"), request.headers.get(WORKER_HEADER, ""),
                   "worker")
        except TokenError as exc:
            raise HTTPException(401, f"only the worker posts to the inbox: {exc}") from None
        try:
            data = _item(json.loads(await request.body()))
        except ValueError:
            raise HTTPException(400, "the request body is not JSON") from None
        pngs, errors = [], []
        for chart_id in dict.fromkeys(data["snapshots"]):  # once each, in order
            try:
                pngs.append((chart_id, await render(chart_id)))
            except SnapshotError as exc:  # the item still goes out, saying what is missing
                errors.append({"chart_id": chart_id, "reason": exc.reason})
        item = await call(store.add_inbox, data["kind"], data["title"], data["body"],
                          data["chart_ids"], pngs)
        announce(item["id"], "worker")
        return {**item, "snapshot_errors": errors}

    @api.get("/inbox/{item_id}")
    async def get_item(item_id: str):
        return JSONResponse(await call(store.get_inbox, item_id_of(item_id)),
                            headers={"Cache-Control": "private, no-store"})

    @api.get("/inbox/{item_id}/snapshots/{n}.png")
    async def snapshot(item_id: str, n: int):
        png = await call(store.inbox_png, item_id_of(item_id), n)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @api.post("/inbox/{item_id}/read")
    async def read_item(item_id: str):
        item = await call(store.read_inbox, item_id_of(item_id),
                          datetime.now(timezone.utc).isoformat(timespec="microseconds"))
        announce(item_id, "user")
        return item

    @api.delete("/inbox/{item_id}", status_code=204)
    async def delete_item(item_id: str):
        await call(store.delete_inbox, item_id_of(item_id))
        announce(item_id, "user")
        return Response(status_code=204)

    return api
