# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The chart document API and its change feed, as one APIRouter over a Store.

`GET/POST /charts`, `GET/PUT/DELETE /charts/{id}`, `GET /charts/{id}/history`,
`POST /charts/{id}/restore/{revision}` and `GET /charts/events`. No auth in
this module: auth.py demands the stack's API pair on every route, app-wide.

Who saved is the `X-Updated-By` header: `user` (the default), `rita`, or a wake's
`rita:watch:<id>` / `rita:schedule:<id>` (chart_tools.caller takes it from the token).
"""
from __future__ import annotations

import asyncio
import json
import re
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from arts_charts.chart_body import BodyError, validate, with_defaults
from arts_charts.store import Conflict, NotFound, Store, is_chart_id

#: A request body larger than this is refused with 413 before it is parsed.
MAX_BYTES = 1_000_000
MAX_TITLE = 200
BY = ("user", "rita")
#: A wake's own name for its saves (spec §1 `updated_by`): rita:watch:<id>, rita:schedule:<id>.
WAKE_BY = re.compile(r"rita:(watch|schedule):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: Seconds between keep-alive comments on an idle event stream.
PING = 15.0
#: Events one subscriber may fall behind before its stream is closed.
BACKLOG = 100


class Feed:
    """Fan-out of change events to every open /charts/events stream.

    ponytail: in-process -- one arts-charts process serves every save. A
    second API process needs a shared feed (Postgres LISTEN/NOTIFY).
    """

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=BACKLOG)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def live(self, queue: asyncio.Queue) -> bool:
        return queue in self._subscribers

    def publish(self, event: dict) -> None:
        """A subscriber too far behind is dropped; its stream ends and the
        client catches up from GET /charts after it reconnects."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)


async def _payload(request: Request) -> tuple[str, dict]:
    """The `{title?, body}` of a POST or PUT, size-capped and validated."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(413, f"a chart document is at most {MAX_BYTES} bytes")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, f"a chart document is at most {MAX_BYTES} bytes")
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "the request body is not JSON") from None
    if not isinstance(data, dict) or "body" not in data or set(data) - {"title", "body"}:
        raise HTTPException(422, 'expected {"title": text, "body": chart/1}')
    title = data.get("title", "")
    if not isinstance(title, str) or len(title) > MAX_TITLE:
        raise HTTPException(422, f"title must be text of at most {MAX_TITLE} characters")
    try:
        validate(data["body"])
    except BodyError as exc:
        raise HTTPException(422, str(exc)) from None
    return title, with_defaults(data["body"])


def _by(request: Request) -> str:
    by = request.headers.get("x-updated-by", "user")
    if by not in BY and not WAKE_BY.fullmatch(by):
        raise HTTPException(400, "X-Updated-By must be 'user', 'rita' or rita:watch:<id>")
    return by


async def _call(fn, *args, missing: str, **kwargs):
    """A store call off the event loop; NotFound is a 404 saying `missing`. The routers bind
    `missing` with functools.partial; a call may still pass its own."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except NotFound:
        raise HTTPException(404, missing) from None


def id_of(value: str, missing: str) -> str:
    """`value` when it is a uuid, as the store mints them; anything else is a 404 `missing`."""
    if not is_chart_id(value):
        raise HTTPException(404, missing)
    return value


def announce(feed: Feed, kind: str, record_id: str, by: str) -> None:
    feed.publish({"kind": kind, "id": record_id, "revision": 0, "by": by})


def _base(request: Request) -> int:
    raw = request.headers.get("if-match")
    if raw is None:
        raise HTTPException(428, "If-Match: <revision> is required")
    try:
        return int(raw.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be a revision number") from None


def documents_router(store: Store, feed: Feed | None = None) -> APIRouter:
    """The routes over `store`, announcing on `feed` (shared with the watch and inbox
    routers, so one /charts/events stream carries every kind)."""
    api = APIRouter()
    feed = Feed() if feed is None else feed

    call = partial(_call, missing="no such chart")  # a missing or deleted chart

    async def write(fn, *args, **kwargs):
        """A store write, announced on the feed. A stale base revision is a
        409 whose body is the current document itself."""
        try:
            doc = await call(fn, *args, **kwargs)
        except Conflict as exc:
            return JSONResponse(exc.current, status_code=409)
        feed.publish({"kind": "chart", "id": doc["id"], "revision": doc["revision"],
                      "by": doc["updated_by"]})
        return doc

    # Declared before /charts/{chart_id}, which would otherwise take "events" as an id.
    @api.get("/charts/events")
    async def events():
        queue = feed.subscribe()

        async def stream():
            try:
                yield "retry: 1000\n\n"
                while feed.live(queue) or not queue.empty():
                    try:
                        event = await asyncio.wait_for(queue.get(), PING)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                feed.unsubscribe(queue)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    @api.get("/charts")
    async def list_charts():
        return await call(store.list)

    @api.post("/charts", status_code=201)
    async def create_chart(request: Request):
        title, body = await _payload(request)
        return await write(store.create, title, body, _by(request))

    @api.get("/charts/{chart_id}")
    async def get_chart(chart_id: str):
        return await call(store.get, chart_id)

    @api.put("/charts/{chart_id}")
    async def put_chart(chart_id: str, request: Request):
        base, by = _base(request), _by(request)
        title, body = await _payload(request)
        return await write(store.save, chart_id, title, body, by, base)

    @api.delete("/charts/{chart_id}")
    async def delete_chart(chart_id: str, request: Request):
        base, by = _base(request), _by(request)
        current = await call(store.get, chart_id)
        return await write(store.save, chart_id, current["title"], current["body"], by, base,
                           deleted=True)

    @api.get("/charts/{chart_id}/history")
    async def chart_history(chart_id: str):
        return await call(store.history, chart_id)

    @api.post("/charts/{chart_id}/restore/{revision}")
    async def restore_chart(chart_id: str, revision: int, request: Request):
        """Write revision `revision` again as the next one, over `If-Match`: a
        restore from a stale view is a 409, exactly like a save."""
        base, by = _base(request), _by(request)
        old = await call(store.revision, chart_id, revision)
        try:
            validate(old["body"])  # the registry or the served intervals may have changed
        except BodyError as exc:
            raise HTTPException(422, f"revision {revision} no longer validates: {exc}") from None
        return await write(store.save, chart_id, old["title"], with_defaults(old["body"]), by, base)

    return api
