# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Run heavy OpenBB routes in a worker process the API can kill (OpenBQ D8).

CFTC and FINRA bond routes do CPU-bound work and build 40-400 MB responses.
In the API process that holds the GIL and the server loop, so /widgets.json
and every other route stall behind them, and nothing can stop a synchronous
pandas section. Here they run in one long-lived child process, the "heavy"
lane: the same openbb-api app, served on a Unix socket. This middleware
forwards the raw request to it and copies the response back; the API only
waits on a socket.

- One request at a time; the rest queue, up to OPENBQ_LANE_QUEUE_MAX, else 503.
- Past OPENBQ_LANE_DEADLINE seconds (queue wait included) the lane is killed,
  the request gets 504, and the lane is respawned. A worker still starting is
  never killed; the request gets 503 instead, unless it has been starting for
  over OPENBQ_LANE_STARTUP_LIMIT seconds (180), when it is replaced.
- A lane over OPENBQ_LANE_RSS_MB after a call is restarted while idle.
- A response over OPENBQ_MAX_RESULT_BYTES is refused with 413.
- OPENBQ_ISOLATE lists the path prefixes; set it empty to run everything in
  process as before.

Hooked in through openbb.toml ``[middleware] hooks``; the worker loads the
same hook with OPENBQ_ROLE=worker and passes everything through.
"""

import asyncio
import atexit
import base64
import glob
import json
import logging
import math
import os
import secrets
import subprocess
import sys
import time
from collections import OrderedDict

import httpx
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

log = logging.getLogger("uvicorn.error")

DEFAULT_ISOLATE = "/api/v1/cftc/,/api/v1/finra/fixedincome/bonds"
# Fixed for the life of the process, yet rebuilt per request upstream: ~5 MB
# of widgets JSON serialized on the server loop, and apps.json does that again
# and then awaits 32 provider apps endpoints on their provider loops (TMX's
# waits behind covered_calls). Under CPU contention each probe took seconds.
# ponytail: edits to workspace_apps.json or widget settings need a restart.
_CATALOGS = {"/widgets.json", "/apps.json"}
# BDOBB's own example dashboards. They use BDOBB built-in cards (note, clock,
# markdown), which openbb-api's /apps.json drops because no backend widget has
# those ids, so they are appended to the built catalog as shipped.
EXTRA_APPS = os.environ.get("OPENBQ_EXTRA_APPS", "/workspace/bdobb_apps.json")
# Cards BDOBB draws itself (its src/lib/builtins.ts, v3 through v10): no
# backend serves them, so they never appear in /widgets.json.
BUILTIN_CARDS = frozenset({
    "note", "markdown", "website", "clock", "rss", "news", "date_probe", "param_echo",
    "period_echo", "local_table", "linked_table", "linked_chart",
})
# BDOBB's logo, the img of the served examples. Workspace fetches app images
# without credentials, so this one path answers without Basic auth.
LOGO_PATH = "/openbq/bdobb-logo.svg"
LOGO_FILE = os.environ.get("OPENBQ_BDOBB_LOGO", "/workspace/bdobb-logo.svg")
# The OpenBQ API's largest table widgets (default response > ~10 MB) served as
# server-paged SSRM tables (approach B): the API itself answers the standard
# OpenBB SSRM contract so BDOBB's "LIVE · paged" provider pages them, and the
# full GET never crosses the caches, the door or the client. The id->route list
# is committed data (lanes/ssrm_widgets.json); a listed id absent from
# /widgets.json is skipped.
SSRM_FILE = os.environ.get("OPENBQ_SSRM_WIDGETS", "/workspace/ssrm_widgets.json")
SSRM_SUFFIX = "/ssrm"
SSRM_CAPS = {"sorting": True, "filtering": ["text", "number"]}


def _load_ssrm_widgets(path=SSRM_FILE) -> dict:
    """{route: widget_id} from the committed list; {} if it is missing or malformed."""
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return {}
    return {e["route"]: e["id"] for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)
            and isinstance(e.get("route"), str)} if isinstance(entries, list) else {}


SSRM_ROUTES = _load_ssrm_widgets()


def _rewrite_widgets(body: bytes) -> bytes:
    """Point each listed widget at <route>/ssrm as an ssrm_table; keep every other field.

    A listed id absent from the catalogue is skipped. Only the three SSRM fields
    are touched, so params, columnsDefs, name and category resolve exactly as before.
    """
    try:
        widgets = json.loads(body)
    except ValueError:
        return body
    if not isinstance(widgets, dict):
        return body
    changed = False
    for route, wid in SSRM_ROUTES.items():
        entry = widgets.get(wid)
        if isinstance(entry, dict):
            entry["type"] = "ssrm_table"
            entry["endpoint"] = route + SSRM_SUFFIX
            entry["ssrm"] = dict(SSRM_CAPS)
            changed = True
    if not changed:
        return body
    # As the API's JSONResponse renders it, so every unlisted widget stays byte-identical.
    return json.dumps(widgets, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


# -- the SSRM rows endpoint ---------------------------------------------------
# POST <route>/ssrm answers the OpenBB SSRM contract for a listed route. The
# full GET runs once per (route, params) through the app itself, so a lane
# route keeps its lane, deadline and size cap and Basic auth still applies;
# the result is kept as a DataFrame and paged, filtered and sorted from there.
# It sits behind the public door, so every request is checked in full before
# anything is acquired, and no parser or exception text is ever reflected.
SSRM_PAGE_MAX = 1000
SSRM_BODY_MAX = 64 << 10  # an SSRM request is a few hundred bytes
SSRM_CACHE_BYTES = int(os.environ.get("OPENBQ_SSRM_CACHE_BYTES", 3 << 30))  # 3 GiB
SSRM_TTL = float(os.environ.get("OPENBQ_SSRM_TTL", 900))                     # 15 minutes
SSRM_DEADLINE = float(os.environ.get("OPENBQ_SSRM_DEADLINE", 300))           # per cold acquisition
SSRM_SLOTS = 2  # cold acquisitions at once: each holds a full result (~1-2 GB for 150 MB of JSON)
SSRM_SORT_MAX = 3     # sortModel entries (BDOBB sends 1; shift-click a few): each is a full sort on the GIL
SSRM_FILTER_MAX = 16  # filterModel entries: each is a full pass over the frame
SSRM_VIEWS = 8      # filtered+sorted row orders kept per frame
_SSRM_TIMEOUT = json.dumps({"detail": "The widget's result did not arrive in time."}).encode()
_SSRM_KEYS = frozenset({"startRow", "endRow", "sortModel", "filterModel", "rowGroupCols",
                        "groupKeys", "valueCols", "pivotCols", "pivotMode"})
_SSRM_GROUP_KEYS = ("rowGroupCols", "groupKeys", "valueCols", "pivotCols")
_SSRM_NUMBER = {"equals": {"filterType", "type", "filter"},
                "inRange": {"filterType", "type", "filter", "filterTo"},
                "greaterThanOrEqual": {"filterType", "type", "filter"},
                "lessThanOrEqual": {"filterType", "type", "filter"}}
_SSRM_REFUSED = ("This widget's table pages, sorts and filters (text contains; number equals, "
                 "range, at least, at most) only; the request was refused.")


class SsrmBadRequest(Exception):
    """A request this endpoint refuses: grouping/values/pivot, a bad filter, or a bad slice."""


class SsrmUpstream(Exception):
    """A non-2xx from the acquisition GET; its status and body (the API's own answer) are kept."""

    def __init__(self, status, body, media_type):
        super().__init__(status)
        self.status, self.body, self.media_type = status, body, media_type


class SsrmCache:
    """(route, params) -> DataFrame, LRU by deep bytes with a TTL and single-flight.

    The acquisition runs as its own task that every caller awaits shielded, so a
    caller that gives up never cancels it for the others sharing it. The newest
    frame is always kept, so the total can pass max_bytes by at most that one
    frame (dropping it would re-run the full GET for every page).

    At most `slots` acquisitions run at once (waiters sharing one take none),
    each within `deadline` seconds; past it every waiter gets the same 504,
    nothing is cached and the slot is freed.
    """

    def __init__(self, max_bytes=SSRM_CACHE_BYTES, ttl=SSRM_TTL, clock=time.monotonic,
                 slots=SSRM_SLOTS, deadline=SSRM_DEADLINE):
        self.max_bytes, self.ttl, self.clock, self.deadline = max_bytes, ttl, clock, deadline
        self.slots = asyncio.Semaphore(slots)
        self.view_slots = asyncio.Semaphore(slots)  # new views copy the frame: keep them off the 3 GiB budget's back
        self.entries = OrderedDict()  # key -> [df, nbytes (frame + its views), expiry, views]
        self.inflight = {}            # key -> asyncio.Task
        self.total = 0

    def fresh(self, key) -> bool:
        """A get() now would be served from the cache, with no acquisition."""
        entry = self.entries.get(key)
        return entry is not None and entry[2] > self.clock()

    def view(self, key, df, view):
        """The kept row order of `view` on this frame, or None."""
        entry = self.entries.get(key)
        if entry is None or entry[0] is not df or view not in entry[3]:
            return None
        entry[3].move_to_end(view)
        return entry[3][view]

    def add_view(self, key, df, view, order):
        """Keep `order` with its frame (at most SSRM_VIEWS, LRU), counted in the byte budget."""
        entry = self.entries.get(key)
        if entry is None or entry[0] is not df:  # the frame is gone: nothing to keep it with
            return
        views = entry[3]
        old = views.pop(view, None)
        delta = order.nbytes - (old.nbytes if old is not None else 0)
        views[view] = order
        while len(views) > SSRM_VIEWS:
            delta -= views.popitem(last=False)[1].nbytes
        entry[1] += delta
        self.total += delta
        self._evict()

    def _evict(self):
        while self.total > self.max_bytes and len(self.entries) > 1:
            self.total -= self.entries.popitem(last=False)[1][1]

    async def get(self, key, acquire):
        if self.fresh(key):
            self.entries.move_to_end(key)
            return self.entries[key][0]
        task = self.inflight.get(key)
        if task is None:
            task = self.inflight[key] = asyncio.ensure_future(self._fill(key, acquire))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())  # retrieved even if every caller left
        return await asyncio.shield(task)

    async def _acquired(self, acquire):
        async with self.slots:
            df = await acquire()
            return df, await asyncio.to_thread(lambda: int(df.memory_usage(deep=True).sum()))

    async def _fill(self, key, acquire):
        try:
            try:  # one deadline from the start: the wait for a slot, the fetch and the build
                df, nbytes = await asyncio.wait_for(self._acquired(acquire), self.deadline)
            except TimeoutError:
                raise SsrmUpstream(504, _SSRM_TIMEOUT, "application/json") from None
            old = self.entries.pop(key, None)
            if old is not None:
                self.total -= old[1]
            self.entries[key] = [df, nbytes, self.clock() + self.ttl, OrderedDict()]
            self.total += nbytes
            self._evict()
            return df
        finally:
            self.inflight.pop(key, None)


SSRM_CACHE = SsrmCache()


def _rows_from(payload):
    """A list of row dicts from an OpenBB response, whatever its envelope."""
    data = payload.get("results") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        return []
    rows = [row for row in data if isinstance(row, dict)]
    return rows if len(rows) == len(data) else []  # mixed/non-dict rows: not a table


async def _acquire(app, route, params, authorization, columns=None):
    """GET the full result ONCE through the app itself, so a lane route keeps its lane.

    With the widget's declared columns, the frame holds exactly those: BDOBB's paged
    provider requires each row's keys to equal columnsDefs, and OpenBB omits None
    fields, so a field absent from every record is added as nulls and undeclared
    fields are dropped (they are never shown)."""
    headers = {"accept-encoding": "identity"}
    if authorization:
        headers["authorization"] = authorization
    # raise_app_exceptions=False: an inner route's crash arrives as its ordinary 500
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://openbq", timeout=None) as client:
        response = await client.get(route, params=params, headers=headers)
    if not response.is_success:
        raise SsrmUpstream(response.status_code, response.content,
                           response.headers.get("content-type", "application/json"))

    def frame():  # off the server loop: a 150 MB parse and frame build take seconds
        import pandas as pd  # here, so the worker role never imports it for the hook
        try:
            payload = json.loads(response.content)
        except ValueError:
            return None
        rows = _rows_from(payload)
        df = pd.DataFrame(rows)
        # An int column with a null is built as float64, which loses ids past 2^53:
        # rebuild it from the parsed ints as nullable Int64.
        for col in df.columns:
            if df[col].dtype == "float64" and df[col].hasnans:
                values = [row.get(col) for row in rows]
                if all(v is None or type(v) is int for v in values):
                    try:
                        df[col] = pd.array(values, dtype="Int64")
                    except (OverflowError, TypeError, ValueError):  # past int64: keep the floats
                        pass
        df = df.reindex(columns=columns) if columns else df
        # The OBBject's warnings (e.g. a provider's record cap) ride every page of this frame.
        warnings = payload.get("warnings") if isinstance(payload, dict) else None
        df.attrs["warnings"] = warnings if isinstance(warnings, list) else []
        return df

    # ponytail: a thread cannot be cancelled, so a build past the deadline keeps
    # running and holding its memory after its slot is freed (ceiling: one extra
    # frame per timed-out build); a process-level build worker could be killed.
    df = await asyncio.to_thread(frame)
    if df is None:
        raise SsrmUpstream(502, json.dumps({"detail": "The widget's result is not JSON."}).encode(),
                           "application/json")
    return df


def _no_constant(_):
    raise ValueError("NaN/Infinity")


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SsrmBadRequest()
    try:
        number = float(value)
    except OverflowError:
        raise SsrmBadRequest() from None
    if not math.isfinite(number):
        raise SsrmBadRequest()
    return number


def _ssrm_body(raw: bytes) -> dict:
    """The SSRM request, checked in full (keys, types, bounds) before anything is acquired."""
    try:
        body = json.loads(raw, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise SsrmBadRequest() from None
    if not isinstance(body, dict) or set(body) != _SSRM_KEYS:
        raise SsrmBadRequest()
    start, end = body["startRow"], body["endRow"]
    if (type(start) is not int or type(end) is not int
            or start < 0 or end < start or end - start > SSRM_PAGE_MAX):
        raise SsrmBadRequest()
    if body["pivotMode"] is not False or any(body[k] != [] for k in _SSRM_GROUP_KEYS):
        raise SsrmBadRequest()
    sorts, filters = body["sortModel"], body["filterModel"]
    if not isinstance(sorts, list) or not isinstance(filters, dict):
        raise SsrmBadRequest()
    for item in sorts:
        if (not isinstance(item, dict) or set(item) != {"colId", "sort"}
                or not isinstance(item["colId"], str) or item["sort"] not in ("asc", "desc")):
            raise SsrmBadRequest()
    if (len(sorts) > SSRM_SORT_MAX or len(filters) > SSRM_FILTER_MAX
            or len({item["colId"] for item in sorts}) != len(sorts)):
        raise SsrmBadRequest()
    for spec in filters.values():
        if not isinstance(spec, dict):
            raise SsrmBadRequest()
        kind, op = spec.get("filterType"), spec.get("type")
        if kind == "text" and op == "contains" and set(spec) == {"filterType", "type", "filter"}:
            if not isinstance(spec["filter"], str):
                raise SsrmBadRequest()
        elif kind == "number" and op in _SSRM_NUMBER and set(spec) == _SSRM_NUMBER[op]:
            _number(spec["filter"])
            if op == "inRange":
                _number(spec["filterTo"])
        else:
            raise SsrmBadRequest()
    return body


def _view_order(df, body):
    """filterModel then sortModel on a checked body: the row positions in order. Unknown columns -> 400."""
    import numpy as np
    import pandas as pd
    if df.empty:  # nothing to page: any column is as good as any other
        return np.arange(0)
    out = df
    for col, spec in body["filterModel"].items():
        if col not in out.columns:
            raise SsrmBadRequest()
        if spec["filterType"] == "text":
            out = out[out[col].astype("string").str.contains(spec["filter"], case=False, na=False, regex=False)]
            continue
        series = pd.to_numeric(out[col], errors="coerce")
        lo = _number(spec["filter"])
        if spec["type"] == "equals" and pd.api.types.is_integer_dtype(out[col]) and lo.is_integer():
            want = int(spec["filter"])  # the parsed value, exact: a float cast loses ids past 2^53
            out = out[out[col] == want] if -2**63 <= want < 2**63 else out.iloc[0:0]
        elif spec["type"] == "equals":
            out = out[series == lo]
        elif spec["type"] == "greaterThanOrEqual":
            out = out[series >= lo]
        elif spec["type"] == "lessThanOrEqual":
            out = out[series <= lo]
        else:
            out = out[(series >= lo) & (series <= _number(spec["filterTo"]))]
    if any(item["colId"] not in out.columns for item in body["sortModel"]):
        raise SsrmBadRequest()
    # One stable pass per column, the last key first, so each column gets its
    # own null placement (AG Grid's: first ascending, last descending) and only
    # a mixed-type column (numbers and "n/a") falls back to text order.
    # ponytail: a NEW view still re-filters and re-sorts the whole frame (seconds
    # of GIL-bound CPU on FINRA/FFIEC sizes); the cache keeps the last SSRM_VIEWS
    # orders per frame so its further pages are a slice. A sorted-index per
    # column would make new views cheap too, if typing a filter proves slow.
    for item in reversed(body["sortModel"]):
        col, asc = item["colId"], item["sort"] == "asc"
        how = {"ascending": asc, "kind": "mergesort", "na_position": "first" if asc else "last"}
        try:
            out = out.sort_values(col, **how)
        except TypeError:
            out = out.sort_values(col, key=lambda s: s.astype("string"), **how)
    return df.index.get_indexer(out.index)


def _ssrm_json_safe(page) -> list:
    """Records of Python values (floats exact; NaN and +/-inf -> None), unlike to_json's 10-digit default."""
    cells = page.astype(object)
    return cells.where(cells.notna() & ~cells.isin([math.inf, -math.inf]), None).to_dict("records")


# widget id -> (its declared param names, its declared columnsDefs fields), None where
# undeclared; from the fixed /widgets.json, so never re-parsed.
_SSRM_WIDGET = {}


async def _declared_params(request, wid):
    """The widget's declared param names, or None when the catalogue does not say."""
    if wid not in _SSRM_WIDGET:
        cache = LANE.catalogs if LANE is not None else _CATALOG_CACHE
        if await _widget_ids(cache, request) is None:
            return None
        entry = json.loads(cache["/widgets.json"][0]).get(wid)
        defs = (((entry.get("data") or {}).get("table") or {}).get("columnsDefs") if isinstance(entry, dict) else None) or []
        fields = [d["field"] for d in defs if isinstance(d, dict) and isinstance(d.get("field"), str)]
        params = entry.get("params") if isinstance(entry, dict) else None
        declared = None
        if isinstance(params, list):
            rows = [p for row in params for p in (row if isinstance(row, list) else [row])]  # grouped rows too
            declared = frozenset(
                p["paramName"] for p in rows if isinstance(p, dict) and isinstance(p.get("paramName"), str))
        _SSRM_WIDGET[wid] = (declared, list(dict.fromkeys(fields)) or None)
    return _SSRM_WIDGET[wid][0]


async def _ssrm(request):
    """POST <route>/ssrm for a listed route; 404 otherwise."""
    route = request.url.path[: -len(SSRM_SUFFIX)]
    if route not in SSRM_ROUTES:
        return _cors(request, JSONResponse({"detail": "Not Found"}, 404))
    # The API's Basic auth is a route dependency, which this hook runs before:
    # check it here, or a cached frame would be served to anyone.
    if not _authorized(request):
        return _unauthorized(request)
    refused = _cors(request, JSONResponse({"detail": _SSRM_REFUSED}, 400))
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > SSRM_BODY_MAX:
            return refused
    try:
        body = _ssrm_body(raw)
    except SsrmBadRequest:
        return refused
    params = request.query_params.multi_items()
    # Only the widget's own params reach the GET and the key: junk params would
    # otherwise each force a fresh full GET of the same data.
    declared = await _declared_params(request, SSRM_ROUTES[route])
    if declared is not None:
        params = [(k, v) for k, v in params if k in declared]
    key = (route, tuple(sorted(params)))
    authorization = request.headers.get("authorization")
    # hit: the frame AND this view's row order came from the cache, so no provider
    # call and no new sort. get() answers a fresh key without awaiting, so this holds.
    hit = SSRM_CACHE.fresh(key)
    view = json.dumps([body["filterModel"], body["sortModel"]], sort_keys=True)
    try:
        df = await SSRM_CACHE.get(key, lambda: _acquire(request.app, route, params, authorization, _SSRM_WIDGET.get(SSRM_ROUTES[route], (None, None))[1]))
        order = SSRM_CACHE.view(key, df, view)
        if order is None:
            hit = False
            async with SSRM_CACHE.view_slots:
                order = await asyncio.to_thread(_view_order, df, body)
            SSRM_CACHE.add_view(key, df, view, order)
        rows = await asyncio.to_thread(lambda: _ssrm_json_safe(df.iloc[order[body["startRow"]:body["endRow"]]]))
        total = len(order)
    except SsrmBadRequest:
        return refused
    except SsrmUpstream as exc:
        return _cors(request, Response(exc.body, exc.status, media_type=exc.media_type))
    page = {"rowData": rows, "rowCount": total}
    if df.attrs.get("warnings"):
        page["warnings"] = df.attrs["warnings"]
    reply = json.dumps(page, allow_nan=False, default=lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v))  # e.g. a timestamp: ISO text
    # Marks a cache hit; the door does not relay this header.
    return _cors(request, Response(reply, 200, media_type="application/json",
                                   headers={"x-openbq-ssrm": "hit" if hit else "miss"}))


# The response's own framing; the API sets its own.
_HOP = {b"content-length", b"transfer-encoding", b"connection", b"keep-alive"}
# Per-caller CORS answers: never cached, _cors() recomputes them per request.
_PER_CALLER = {b"vary"}


def _rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _apps(body: bytes):
    """(apps, extended): the built apps.json list, plus EXTRA_APPS when that is a list too.
    (None, False) when the build is not a JSON list."""
    try:
        apps = json.loads(body)
    except ValueError:
        return None, False
    if not isinstance(apps, list):
        return None, False
    try:
        with open(EXTRA_APPS, encoding="utf-8") as f:
            extra = json.load(f)
    except (OSError, ValueError):
        return apps, False
    return (apps + extra, True) if isinstance(extra, list) else (apps, False)


def _cards(app) -> set:
    """The widget ids of an app's cards, over every tab."""
    tabs = app.get("tabs") if isinstance(app, dict) else None
    if not isinstance(tabs, dict):
        return set()
    return {card.get("i") for tab in tabs.values() if isinstance(tab, dict)
            for card in tab.get("layout") or [] if isinstance(card, dict)}


def _servable_apps(apps: list, widget_ids) -> list:
    """Drop every app with a card that is neither in /widgets.json nor a BDOBB built-in.

    A provider that is not installed would otherwise ship its apps as blank
    cards: openbb-api keeps an app when any one of its tabs resolves.
    """
    kept = []
    for app in apps:
        missing = sorted(map(str, _cards(app) - BUILTIN_CARDS - widget_ids))
        if missing:
            log.warning("OpenBQ apps.json: dropped app %r: no widget in /widgets.json for %s",
                        app.get("name"), ", ".join(missing))
        else:
            kept.append(app)
    return kept


async def _widget_ids(cache, request):
    """The ids /widgets.json serves, from the catalog cache (built through the app if need be)."""
    if "/widgets.json" not in cache:
        transport = httpx.ASGITransport(app=request.app)
        # The caller's Authorization (already checked), or the API's own auth refuses the build.
        auth = request.headers.get("authorization")
        async with httpx.AsyncClient(transport=transport, base_url="http://openbq") as client:
            await client.get("/widgets.json", headers={"authorization": auth} if auth else None)
    if "/widgets.json" not in cache:
        return None
    try:
        widgets = json.loads(cache["/widgets.json"][0])
    except ValueError:
        return None
    return set(widgets) if isinstance(widgets, dict) else None


def _logo(request):
    """BDOBB's logo, without credentials (Workspace fetches app images without them)."""
    try:
        with open(LOGO_FILE, "rb") as f:
            svg = f.read()
    except OSError:
        return _cors(request, JSONResponse({"detail": "Not Found"}, 404))
    return _cors(request, Response(svg, 200, media_type="image/svg+xml",
                                   headers={"Cache-Control": "public, max-age=86400"}))


def _is_catalog(request) -> bool:
    return request.method == "GET" and request.url.path in _CATALOGS and not request.url.query


async def _catalog(cache, request, call_next):
    """Serve /widgets.json and /apps.json from their first successful build."""
    if not _authorized(request):  # the cache must not outlive the API's own Basic auth
        return _unauthorized(request)
    path = request.url.path
    if path not in cache:
        response = await call_next(request)
        if response.status_code != 200:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if path == "/widgets.json":
            body = _rewrite_widgets(body)
        elif path == "/apps.json":
            apps, extended = _apps(body)
            if extended:
                body = json.dumps(apps).encode()
            if apps is not None and any(_cards(app) - BUILTIN_CARDS for app in apps):
                widget_ids = await _widget_ids(cache, request)
                if widget_ids is None:  # no widget catalog yet: serve as built, cache nothing
                    log.warning("OpenBQ apps.json: /widgets.json unavailable, apps not checked")
                    return _cors(request, Response(body, 200, media_type="application/json"))
                kept = _servable_apps(apps, widget_ids)
                if len(kept) < len(apps):
                    body = json.dumps(kept).encode()
        cache[path] = (body, [
            (k, v) for k, v in response.raw_headers
            if k.lower() not in _HOP | _PER_CALLER and not k.lower().startswith(b"access-control-")
        ])
    body, headers = cache[path]
    response = Response(body, 200)
    response.raw_headers = [*headers, (b"content-length", str(len(body)).encode())]
    return _cors(request, response)


def _unauthorized(request):
    return _cors(request, JSONResponse({"detail": "Unauthorized"}, 401, {"WWW-Authenticate": "Basic"}))


def _cors(request, response):
    """openbb-api adds [middleware] hooks outside its CORSMiddleware, so answers made here pass through it."""
    for entry in getattr(request.app, "user_middleware", []):
        if entry.cls is CORSMiddleware:
            return CORSMiddleware(response, *entry.args, **entry.kwargs)
    return response


def _authorized(request) -> bool:
    """The status endpoint follows the API's Basic auth when it is on."""
    if os.environ.get("OPENBB_API_AUTH", "").lower() not in ("1", "true", "yes"):
        return True
    expected = f"{os.environ.get('OPENBB_API_USERNAME', '')}:{os.environ.get('OPENBB_API_PASSWORD', '')}"
    given = request.headers.get("authorization", "")
    return secrets.compare_digest(
        given.encode(), b"Basic " + base64.b64encode(expected.encode())
    )


class Lane:
    """One worker process serving the allowlisted routes one request at a time."""

    def __init__(self, command, socket, prefixes, deadline=165.0, queue_max=16,
                 rss_mb=3584.0, max_bytes=256 << 20, shard_dir=None, name="heavy",
                 startup_limit=180.0):
        self.command, self.socket, self.prefixes = command, socket, prefixes
        self.deadline, self.queue_max, self.rss_mb = deadline, queue_max, rss_mb
        self.max_bytes, self.shard_dir, self.name = max_bytes, shard_dir, name
        self.startup_limit = startup_limit
        self.spawned_at = 0.0
        self.proc = None
        self.lock = asyncio.Lock()
        self.waiting = 0
        self.restarts = 0
        self.last_kill = None
        self._client = None
        self._monitor = None
        self._ready_pid = None
        self.catalogs = {}

    # -- process -----------------------------------------------------------

    def start(self):
        """Spawn the worker. Its own startup (the platform import) is awaited per request."""
        if self.shard_dir:  # temp files of a killed writer (openbb_cftc/utils/store.py)
            for orphan in glob.glob(os.path.join(self.shard_dir, "*.tmp*")):
                os.remove(orphan)
        if os.path.exists(self.socket):
            os.remove(self.socket)
        os.makedirs(os.path.dirname(self.socket), exist_ok=True)
        self.proc = subprocess.Popen(self.command, env={**os.environ, "OPENBQ_ROLE": "worker"})
        self.spawned_at = time.monotonic()
        log.info("OpenBQ lane %s: worker pid %s starting", self.name, self.proc.pid)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    async def _restart(self, reason: str):
        """Kill and respawn off the server loop: reaping a worker stuck in I/O can block."""
        self.last_kill = {"reason": reason, "pid": self.proc.pid if self.proc else None, "at": time.time()}
        self.restarts += 1
        await asyncio.get_running_loop().run_in_executor(None, lambda: (self.stop(), self.start()))

    async def _ready(self):
        """Wait until the worker accepts connections (any HTTP answer will do)."""
        while self._ready_pid != self.proc.pid:
            if self.proc.poll() is not None:
                raise httpx.ConnectError("lane worker exited during startup")
            try:
                await self._http().get("/openbq/ready", timeout=5)
                self._ready_pid = self.proc.pid
            except httpx.TransportError:
                await asyncio.sleep(0.2)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=self.socket), base_url="http://lane", timeout=None
            )
        return self._client

    def status(self) -> dict:
        alive = self.proc is not None and self.proc.poll() is None
        return {self.name: {
            "pid": self.proc.pid if alive else None,
            "rss_mb": round(_rss_mb(self.proc.pid), 1) if alive else None,
            "busy": self.lock.locked(), "queued": self.waiting,
            "restarts": self.restarts, "last_kill": self.last_kill,
        }}

    # -- requests ----------------------------------------------------------

    async def handle(self, request, call_next):
        if self._monitor is None:
            self._monitor = asyncio.ensure_future(_watch_loop_lag())
        path = request.url.path
        if path == "/openbq/lanes":
            if not _authorized(request):
                return _unauthorized(request)
            return _cors(request, JSONResponse(self.status()))
        if _is_catalog(request):
            return await _catalog(self.catalogs, request, call_next)
        if (request.method == "OPTIONS" or path.endswith("_choices")
                or not any(path.startswith(p) for p in self.prefixes)):
            return await call_next(request)

        body = await request.body()
        until = time.monotonic() + self.deadline
        if self.waiting >= self.queue_max:
            return self._answer(503, "The heavy-route lane's queue is full.", request, "queue-503")
        self.waiting += 1
        try:
            await asyncio.wait_for(self.lock.acquire(), self.deadline)
        except TimeoutError:
            return self._answer(503, "The heavy-route lane stayed busy past this request's deadline.",
                                request, "queue-503")
        finally:
            self.waiting -= 1
        # Shielded: a client that gives up does not cancel the call, so the
        # lane is never handed a second request while the first still runs.
        return await asyncio.shield(asyncio.ensure_future(self._run(request, body, until)))

    async def _run(self, request, body, until):
        queued = time.monotonic() - (until - self.deadline)
        started, outcome, size, status = time.monotonic(), "ok", 0, 0
        try:
            if self.proc is None or self.proc.poll() is not None:
                await self._restart("worker exited")
            elif (self._ready_pid != self.proc.pid
                  and time.monotonic() - self.spawned_at > self.startup_limit):
                await self._restart(f"not started within {self.startup_limit:g} s")
            try:
                status, headers, data = await asyncio.wait_for(
                    self._exchange(request, body), until - time.monotonic()
                )
            except TimeoutError:
                if self._ready_pid != self.proc.pid:
                    # Still importing the platform (~30 s): killing it would only
                    # start that over, and every later request would time out too.
                    outcome = "starting-503"
                    return self._error(request, 503, "The heavy-route worker is still starting.")
                outcome = "killed-504"
                await self._restart("deadline")
                return self._error(request, 504, f"The request did not finish within {self.deadline:g} seconds.")
            except httpx.TransportError:
                outcome = "died-502"
                await self._restart("worker died")
                return self._error(request, 502, "The heavy-route worker died during the request; it has been restarted.")
            if data is None:
                outcome = "too-large-413"
                return self._error(request, 413, f"The result is larger than {self.max_bytes} bytes.")
            size = len(data)
            response = Response(data, status)
            response.raw_headers = [h for h in headers if h[0].lower() not in _HOP]
            response.raw_headers.append((b"content-length", str(size).encode()))
            return response
        finally:
            try:
                pid = self.proc.pid if self.proc else None
                rss = _rss_mb(pid) if pid else 0.0
                log.info(
                    "OpenBQ lane %s: %s %s status=%s outcome=%s queue_ms=%d run_ms=%d bytes=%d pid=%s rss_mb=%.0f",
                    self.name, request.method, request.url.path, status, outcome,
                    queued * 1000, (time.monotonic() - started) * 1000, size, pid, rss,
                )
                if outcome == "ok" and rss > self.rss_mb:
                    await self._restart(f"rss {rss:.0f} MB over {self.rss_mb:g} MB")
            finally:
                self.lock.release()

    async def _exchange(self, request, body):
        """Send the raw request to the worker; return (status, headers, body or None if too large)."""
        await self._ready()
        headers = [(k, v) for k, v in request.headers.raw if k.lower() not in _HOP]
        if b"accept-encoding" not in (k.lower() for k, _ in headers):
            headers.append((b"accept-encoding", b"identity"))  # not httpx's own gzip default
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        async with self._http().stream(request.method, url, headers=headers, content=body) as response:
            if int(response.headers.get("content-length", 0)) > self.max_bytes:
                return response.status_code, [], None
            chunks, size = [], 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > self.max_bytes:
                    return response.status_code, [], None
                chunks.append(chunk)
            return response.status_code, response.headers.raw, b"".join(chunks)

    def _error(self, request, status, detail):
        headers = {"Retry-After": "30"} if status == 503 else None
        return _cors(request, JSONResponse({"detail": detail}, status, headers))

    def _answer(self, status, detail, request, outcome):
        log.info("OpenBQ lane %s: %s %s status=%s outcome=%s", self.name, request.method,
                 request.url.path, status, outcome)
        return self._error(request, status, detail)


async def _watch_loop_lag(interval=0.1, threshold=0.25):
    """Log any server-loop pause over 250 ms: the wedge alarm."""
    while True:
        before = time.monotonic()
        await asyncio.sleep(interval)
        lag = time.monotonic() - before - interval
        if lag > threshold:
            log.warning("OpenBQ loop lag: the server loop paused %.2f s", lag)


def _shard_dir():
    try:
        from openbb_core.app.utils import get_user_cache_directory

        return os.path.join(get_user_cache_directory(), "cftc", "dtcc", "record_shards")
    except Exception:  # noqa: BLE001  no cache directory, nothing to sweep
        return None


LANE = None
_CATALOG_CACHE = {}  # used when no lane is configured (OPENBQ_ISOLATE empty)
_prefixes = [p for p in os.environ.get("OPENBQ_ISOLATE", DEFAULT_ISOLATE).split(",") if p.strip()]
if os.environ.get("OPENBQ_ROLE") != "worker" and _prefixes:
    _socket = os.environ.get("OPENBQ_LANE_SOCKET", "/run/openbq/heavy.sock")
    LANE = Lane(
        [os.path.join(os.path.dirname(sys.executable), "openbb-api"), "--uds", _socket],
        _socket,
        [p.strip() for p in _prefixes],
        deadline=float(os.environ.get("OPENBQ_LANE_DEADLINE", 165)),
        queue_max=int(os.environ.get("OPENBQ_LANE_QUEUE_MAX", 16)),
        rss_mb=float(os.environ.get("OPENBQ_LANE_RSS_MB", 3584)),
        max_bytes=int(os.environ.get("OPENBQ_MAX_RESULT_BYTES", 256 << 20)),
        shard_dir=_shard_dir(),
        startup_limit=float(os.environ.get("OPENBQ_LANE_STARTUP_LIMIT", 180)),
    )
    LANE.start()  # eagerly: its platform import overlaps the API's own
    atexit.register(LANE.stop)


PROVIDERS_PATH = "/providers.json"
_OPTIONAL = frozenset({"cftc", "econdb"})  # bls is key-required
_LOCAL = frozenset({"deltalake", "kdb"})
_NAMES = {
    "yfinance": "Yahoo Finance", "sec": "SEC", "federal_reserve": "Federal Reserve",
    "imf": "IMF", "oecd": "OECD", "government_us": "US Government", "fmp": "FMP",
    "fred": "FRED", "tiingo": "Tiingo", "eia": "EIA", "bls": "BLS", "cftc": "CFTC",
    "congress_gov": "Congress.gov", "econdb": "EconDB", "intrinio": "Intrinio",
    "benzinga": "Benzinga", "tradingeconomics": "TradingEconomics", "eodhd": "EODHD",
    "deltalake": "Delta Lake", "kdb": "kdb+",
}


def provider_descriptor(credentials: dict) -> list:
    """key-maint's provider inventory (Episode 3): which providers this API has
    and which credential names each takes. Names only; no value is read.
    Unit-tested in key-maint/tests/test_providers_route.py."""
    out = []
    for pid in sorted(credentials):
        names = list(credentials[pid])
        auth = ("optional" if pid in _OPTIONAL else "required") if names else "not_required"
        out.append({"id": pid, "name": _NAMES.get(pid, pid.replace("_", " ").title()),
                    "credentials": names, "env_vars": [c.upper() for c in names],
                    "auth": auth, "local": pid in _LOCAL})
    return out


def _provider_credentials() -> dict:
    from openbb_core.app.provider_interface import ProviderInterface  # the API process only
    return ProviderInterface().credentials


async def middleware(request, call_next):
    """openbb.toml [middleware] hook."""
    if request.url.path == LOGO_PATH and request.method in ("GET", "HEAD"):
        return _logo(request)
    if request.method == "GET" and request.url.path == PROVIDERS_PATH:
        if not _authorized(request):
            return _unauthorized(request)
        return _cors(request, JSONResponse(provider_descriptor(_provider_credentials())))
    if request.method == "POST" and request.url.path.endswith(SSRM_SUFFIX):
        return await _ssrm(request)  # before the lane, which would forward it to a worker with no such route
    if LANE is not None:
        return await LANE.handle(request, call_next)
    if _is_catalog(request):  # with the lane off, the catalogs keep their cache and BDOBB examples
        return await _catalog(_CATALOG_CACHE, request, call_next)
    return await call_next(request)
