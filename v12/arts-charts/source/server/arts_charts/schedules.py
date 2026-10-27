# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Schedules (spec §4): a pack of charts Rita reports on at a New York time.

Over HTTP: `GET /schedules`, `POST /schedules`, `PATCH /schedules/{id}`,
`DELETE /schedules/{id}` -- what Rita's schedule tools call. Each change is
announced on /charts/events as `{kind: "schedule", id, revision: 0, by}`.
Only the worker (arts_charts.worker) runs them.

`when` is `daily HH:MM`, `weekdays HH:MM` or `sessions HH:MM` (trading days
on the server's XNYS calendar), 24-hour New York wall-clock time. An
occurrence is keyed by its New York date and time (`2026-10-14T16:30`) and
runs once: the worker claims it by a unique `(schedule_id, occurrence)` row.

DST: a time is read with Python's PEP 495 default (fold=0). On the
spring-forward day a time inside the skipped hour (02:30) is read with the
offset from before the jump and runs once at 03:30 EDT; on the fall-back
day a time inside the repeated hour (01:30) runs at its first pass, and the
second pass has the same key, so it does not run again.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response

from arts_charts.calendar import UsEquitySessions
from arts_charts.classify import classify
from arts_charts.documents import Feed, _by
from arts_charts.store import NotFound, Store, is_chart_id

MAX_NOTE = 500
#: Charts in one schedule: each is described for Rita and pictured in the item.
MAX_CHARTS = 8
#: More schedules than this is a runaway loop, not a person.
MAX_SCHEDULES = 100
_TYPES = {"chart_ids": list, "when": str, "note": str, "enabled": bool}

NY = ZoneInfo("America/New_York")
_WHEN = re.compile(r"\s*(daily|weekdays|sessions)\s+([01]\d|2[0-3]):([0-5]\d)\s*")
NO_CALENDAR = UsEquitySessions(classify)  # every weekday is a session; the worker passes its own
#: `sessions` follows the calendar of a US listing: XNYS, the one equity calendar here.
_XNYS = "SPY"


class WhenError(ValueError):
    """A `when` that is not the grammar; the API answers it with 422."""


def _parse(text) -> tuple[str, time]:
    m = _WHEN.fullmatch(text) if isinstance(text, str) else None
    if m is None:
        raise WhenError("when is 'daily HH:MM', 'weekdays HH:MM' or 'sessions HH:MM' "
                        "(trading days), 24-hour New York time")
    return m.group(1), time(int(m.group(2)), int(m.group(3)))


def normal(text) -> str:
    """`text` as stored: `<kind> HH:MM`; WhenError when it is not the grammar."""
    kind, at = _parse(text)
    return f"{kind} {at:%H:%M}"


def _runs_on(kind: str, day, sessions) -> bool:
    if kind == "daily":
        return True
    if kind == "weekdays":
        return day.weekday() < 5
    return sessions.is_open(_XNYS, day)


def latest(when: str, now: datetime, sessions=NO_CALENDAR) -> tuple[str, datetime] | None:
    """The latest occurrence of `when` at or before `now` (aware): its key, the New York
    date and time, and its instant in UTC. None only if none falls in the last week."""
    kind, at = _parse(when)
    today = now.astimezone(NY).date()
    for back in range(8):
        day = today - timedelta(days=back)
        instant = datetime.combine(day, at, tzinfo=NY).astimezone(timezone.utc)
        if instant <= now and _runs_on(kind, day, sessions):
            return f"{day.isoformat()}T{at:%H:%M}", instant
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


async def _fields(request: Request, allowed: set[str]) -> dict:
    """The request's schedule fields, typed and in normal form; 422 with the reason."""
    try:
        data = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, "the request body is not JSON") from None
    if not isinstance(data, dict) or set(data) - allowed:
        raise HTTPException(422, f"a schedule takes only {', '.join(sorted(allowed))}")
    for key, value in data.items():
        if not isinstance(value, _TYPES[key]):
            raise HTTPException(422, f"{key} must be {_TYPES[key].__name__}")
    if "chart_ids" in data:
        ids = data["chart_ids"]
        if not (0 < len(ids) <= MAX_CHARTS and len(set(map(str, ids))) == len(ids)
                and all(isinstance(i, str) and is_chart_id(i) for i in ids)):
            raise HTTPException(422, f"chart_ids is a list of 1-{MAX_CHARTS} distinct chart ids")
    if "note" in data and len(data["note"]) > MAX_NOTE:
        raise HTTPException(422, f"note is at most {MAX_NOTE} characters")
    if "when" in data:
        try:
            data["when"] = normal(data["when"])
        except WhenError as exc:
            raise HTTPException(422, str(exc)) from None
    return data


def schedules_router(store: Store, feed: Feed) -> APIRouter:
    api = APIRouter()

    async def call(fn, *args, missing="no such schedule"):
        try:
            return await asyncio.to_thread(fn, *args)
        except NotFound:
            raise HTTPException(404, missing) from None

    async def charts_exist(chart_ids: list[str]) -> None:
        for chart_id in chart_ids:
            await call(store.get, chart_id, missing=f"no such chart: {chart_id}")

    def announce(schedule_id: str, by: str) -> None:
        feed.publish({"kind": "schedule", "id": schedule_id, "revision": 0, "by": by})

    def schedule_id_of(schedule_id: str) -> str:
        if not is_chart_id(schedule_id):  # a uuid, as create_schedule mints
            raise HTTPException(404, "no such schedule")
        return schedule_id

    @api.get("/schedules")
    async def list_schedules():
        return {"schedules": await call(store.list_schedules)}

    @api.post("/schedules", status_code=201)
    async def create_schedule(request: Request):
        by, data = _by(request), await _fields(request, set(_TYPES))
        if "chart_ids" not in data or "when" not in data:
            raise HTTPException(422, "a schedule needs chart_ids and when")
        await charts_exist(data["chart_ids"])
        if len(await call(store.list_schedules)) >= MAX_SCHEDULES:
            raise HTTPException(422, f"at most {MAX_SCHEDULES} schedules")
        schedule = await call(store.create_schedule, data["chart_ids"], data["when"],
                              data.get("note", ""), data.get("enabled", True), _now())
        announce(schedule["id"], by)
        return schedule

    @api.patch("/schedules/{schedule_id}")
    async def update_schedule(schedule_id: str, request: Request):
        """Change some fields. A new `when`, or enabling it again, re-arms it: only
        occurrences from now on run, so a change never sets off a report late."""
        by, data = _by(request), await _fields(request, set(_TYPES))
        schedule = await call(store.get_schedule, schedule_id_of(schedule_id))
        await charts_exist(data.get("chart_ids", []))
        if (data.get("when", schedule["when"]) != schedule["when"]
                or (data.get("enabled") and not schedule["enabled"])):
            data["armed_at"] = _now()
        await call(store.set_schedule, schedule_id, data)
        announce(schedule_id, by)
        return await call(store.get_schedule, schedule_id)

    @api.delete("/schedules/{schedule_id}", status_code=204)
    async def delete_schedule(schedule_id: str, request: Request):
        by = _by(request)
        await call(store.delete_schedule, schedule_id_of(schedule_id))
        announce(schedule_id, by)
        return Response(status_code=204)

    return api
