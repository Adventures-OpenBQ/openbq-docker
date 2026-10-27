# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Watches (spec §3) over HTTP: what Rita's watch tools call, and the ntfy buttons.

`GET /watches?chart_id=`, `POST /watches`, `PATCH /watches/{id}`,
`DELETE /watches/{id}`, and `POST /watches/action` -- the push buttons, which
carry an action token instead of the user's session. A watch is checked
against its chart on every save; only the worker (arts_charts.worker)
evaluates watches. Each change is announced on /charts/events as
`{kind: "watch", id, revision: 0, by}` so an open card can count its bell.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response

from arts_charts.conditions import ConditionError, parse, resolve
from arts_charts.documents import Feed, _by
from arts_charts.store import NotFound, Store, is_chart_id
from arts_charts.tokens import TokenError, verify

MAX_NOTE = 500
DEFAULT_COOLDOWN = 3600
MAX_COOLDOWN = 30 * 86400
#: More watches than this is a runaway loop, not a person.
MAX_WATCHES = 200
#: How long the Mute button mutes (spec §3: "Mute 1 day").
MUTE = timedelta(days=1)
#: Why an AVWAP condition is refused (P6): the registry's AVWAP is null without trade data.
NO_TICKS = "AVWAP needs trade data; this server has no tick source yet"
_TYPES = {"chart_id": str, "condition": str, "note": str, "cooldown": int, "enabled": bool}


async def _fields(request: Request, allowed: set[str]) -> dict:
    try:
        data = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, "the request body is not JSON") from None
    if not isinstance(data, dict) or set(data) - allowed:
        raise HTTPException(422, f"a watch takes only {', '.join(sorted(allowed))}")
    for key, value in data.items():
        if not isinstance(value, _TYPES[key]) or (key == "cooldown" and isinstance(value, bool)):
            raise HTTPException(422, f"{key} must be {_TYPES[key].__name__}")
    if "note" in data and len(data["note"]) > MAX_NOTE:
        raise HTTPException(422, f"note is at most {MAX_NOTE} characters")
    if "cooldown" in data and not 0 <= data["cooldown"] <= MAX_COOLDOWN:
        raise HTTPException(422, f"cooldown is 0-{MAX_COOLDOWN} seconds")
    return data


def watches_router(store: Store, feed: Feed) -> APIRouter:
    api = APIRouter()

    async def call(fn, *args, missing="no such watch", **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except NotFound:
            raise HTTPException(404, missing) from None

    async def checked(chart_id: str, condition: str, written: bool = True) -> None:
        """422 unless `condition` resolves on the chart as it is now. AVWAP is refused only
        in a condition being written: a watch stored before that can still be edited or disabled."""
        if not is_chart_id(chart_id):
            raise HTTPException(404, "no such chart")
        doc = await call(store.get, chart_id, missing="no such chart")
        try:
            resolved = resolve(parse(condition), doc["body"])
            if written and "avwap" in (resolved.left.name, resolved.right.name):
                raise ConditionError(NO_TICKS)  # ponytail: drop when a tick source exists
        except ConditionError as exc:
            raise HTTPException(422, str(exc)) from None

    def announce(watch_id: str, by: str) -> None:
        feed.publish({"kind": "watch", "id": watch_id, "revision": 0, "by": by})

    def watch_id_of(watch_id: str) -> str:
        if not is_chart_id(watch_id):  # a uuid, as create_watch mints
            raise HTTPException(404, "no such watch")
        return watch_id

    @api.get("/watches")
    async def list_watches(chart_id: str | None = None):
        return {"watches": await call(store.list_watches, chart_id)}

    @api.post("/watches", status_code=201)
    async def create_watch(request: Request):
        by, data = _by(request), await _fields(request, set(_TYPES))
        if "chart_id" not in data or "condition" not in data:
            raise HTTPException(422, "a watch needs chart_id and condition")
        await checked(data["chart_id"], data["condition"])
        if len(await call(store.list_watches)) >= MAX_WATCHES:
            raise HTTPException(422, f"at most {MAX_WATCHES} watches")
        watch = await call(store.create_watch, data["chart_id"], data["condition"],
                           data.get("note", ""), data.get("cooldown", DEFAULT_COOLDOWN),
                           data.get("enabled", True))
        announce(watch["id"], by)
        return watch

    @api.patch("/watches/{watch_id}")
    async def update_watch(watch_id: str, request: Request):
        """Change some fields. The condition is checked again, and any change clears an
        error: whatever was wrong, the user or Rita has just looked at it."""
        by, data = _by(request), await _fields(request, set(_TYPES) - {"chart_id"})
        watch = await call(store.get_watch, watch_id_of(watch_id))
        await checked(watch["chart_id"], data.get("condition", watch["condition"]),
                      written="condition" in data)
        await call(store.set_watch, watch_id, {**data, "state": "ok", "error": None,
                                               "failures": 0})
        announce(watch_id, by)
        return await call(store.get_watch, watch_id)

    @api.delete("/watches/{watch_id}", status_code=204)
    async def delete_watch(watch_id: str, request: Request):
        by = _by(request)
        await call(store.delete_watch, watch_id_of(watch_id))
        announce(watch_id, by)
        return Response(status_code=204)

    @api.post("/watches/action")
    async def watch_action(request: Request):
        """An ntfy button: `{"token"}`, a token for one watch and one action. Pressing a
        button twice is harmless: Mute re-arms one day from now, and Snapshot now
        coalesces with a request the worker has not taken yet."""
        try:
            token = json.loads(await request.body())["token"]
            assert isinstance(token, str)
        except (ValueError, KeyError, TypeError, AssertionError):
            raise HTTPException(422, 'expected {"token": text}') from None
        secret = os.environ.get("ARTS_CHARTS_SECRET")
        if not secret:
            raise HTTPException(503, "ARTS_CHARTS_SECRET is not set")
        try:
            claims = verify(secret, token, "action")
        except TokenError as exc:
            raise HTTPException(401, str(exc)) from None
        watch_id, what = claims.get("watch"), claims.get("action")
        if what not in ("mute", "snapshot"):
            raise HTTPException(422, "the action is mute or snapshot")
        watch = await call(store.get_watch, watch_id_of(str(watch_id)))
        now = datetime.now(timezone.utc)
        if what == "mute":
            until = (now + MUTE).isoformat(timespec="microseconds")
            await call(store.set_watch, watch_id, {"muted_until": until})
            announce(watch_id, "user")
            return {"status": "muted", "watch_id": watch_id}
        asked = await call(store.set_watch, watch["id"],
                           {"snapshot_requested_at": now.isoformat(timespec="microseconds")},
                           where={"snapshot_requested_at": None})
        return {"status": "requested" if asked else "already requested", "watch_id": watch_id}

    return api
