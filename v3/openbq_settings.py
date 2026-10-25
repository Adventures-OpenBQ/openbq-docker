# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""BDOBB key-mode user settings, dashboards and apps.

Settings: GET /pro/user and POST /pro/display-settings. Dashboards: GET /pro/dash/sync/owned,
GET /pro/dash/sync/shared, POST /pro/dash/sync (items upsert and delete). Apps: GET /pro/user-apps/sync
returns owned + shared in Workspace's UserAppReturn shape; POST and DELETE /pro/user-apps/{uuid}
upsert (body = content) and delete one app.

System dashboards (v8): GET, PUT and DELETE /pro/dash/sync/system/{id}, where {id} is a reserved
name (only "docks" at v8, BDOBB's locked-widget bands). One per credential, stored with
"hidden": true beside the ordinary dashboards; GET /pro/dash/sync/owned never lists a hidden one
and POST /pro/dash/sync cannot reach one (its keys are uuids). A PUT carries the client's own
"revision" (a non-negative integer, BDOBB's edit time in ms) and the newest revision wins: an older
one answers 409 with the stored dashboard. DELETE takes the same check as ?revision=<n>.

Authorised by the API's own Basic credential (OPENBB_API_AUTH with OPENBB_API_USERNAME and
OPENBB_API_PASSWORD). With API auth off there is no key to check, so all routes answer 404,
as on a backend without a settings API. One JSON object per credential, kept as sent on the
persistent user-data volume.
"""
import base64
import binascii
import hashlib
import json
import os
import secrets
import threading
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path

from starlette.responses import JSONResponse

STORE = Path(os.environ.get("OPENBQ_SETTINGS_DIR", "/root/OpenBBUserData/bdobb-settings"))
MAX_BYTES = 1_000_000
PATHS = {"/pro/user", "/pro/display-settings", "/pro/dash/sync", "/pro/dash/sync/owned",
         "/pro/dash/sync/shared", "/pro/user-apps/sync"}
APP_PREFIX = "/pro/user-apps/"
SYSTEM_PREFIX = "/pro/dash/sync/system/"
SYSTEM_IDS = {"docks"}
MAX_SYNC_BYTES = 5_000_000
# ponytail: one process-wide lock around every dashboard/app read-modify-write; per-credential locks if it ever contends.
LOCK = threading.Lock()


def _credential(request) -> str | None:
    """Return 'user:password' when the request carries the API's Basic credential."""
    from openbb_core.env import Env

    env = Env()
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        user, _, password = base64.b64decode(value, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    ok_user = secrets.compare_digest(user.encode(), (env.API_USERNAME or "").encode())
    ok_password = secrets.compare_digest(password.encode(), (env.API_PASSWORD or "").encode())
    return f"{user}:{password}" if ok_user and ok_password else None


def _cors(request, response):
    """Add the allow-origin header ODP's CORS layer would add (hooks run outside it)."""
    from openbb_core.app.service.system_service import SystemService

    origin = request.headers.get("origin")
    allowed = SystemService().system_settings.api_settings.cors.allow_origins
    if origin and "*" in allowed:
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


async def middleware(request, call_next):
    """Serve the settings, dashboard and app routes; pass every other request (and preflight) through."""
    from openbb_core.env import Env

    path = request.url.path
    if (not (path in PATHS or path.startswith(APP_PREFIX) or path.startswith(SYSTEM_PREFIX))
            or request.method == "OPTIONS" or not Env().API_AUTH):
        return await call_next(request)
    return _cors(request, await _settings(request))


async def _settings(request):
    """Answer one authorised settings request."""
    credential = _credential(request)
    if credential is None:
        return JSONResponse({"detail": "Invalid or missing credentials."}, status_code=401,
                            headers={"WWW-Authenticate": "Basic"})
    key = hashlib.sha256(credential.encode()).hexdigest()
    user = credential.partition(":")[0]
    route = (request.method, request.url.path)
    if route == ("GET", "/pro/dash/sync/owned"):
        return JSONResponse({"owned": _owned(_load(STORE / f"{key}.dashboards.json"), user)})
    if route == ("GET", "/pro/dash/sync/shared"):
        return JSONResponse({"shared": {}, "entity_shared": {}})
    if route == ("POST", "/pro/dash/sync"):
        return await _post_dashboards(request, STORE / f"{key}.dashboards.json")
    if route == ("GET", "/pro/user-apps/sync"):
        return JSONResponse({"owned": _owned_apps(_load(STORE / f"{key}.apps.json"), user), "shared": {}})
    if request.url.path.startswith(SYSTEM_PREFIX):
        return await _system(request, STORE / f"{key}.dashboards.json", request.url.path[len(SYSTEM_PREFIX):], user)
    if request.url.path.startswith(APP_PREFIX) and request.method in ("POST", "DELETE"):
        return await _app(request, STORE / f"{key}.apps.json", request.url.path[len(APP_PREFIX):])
    path = STORE / f"{key}.json"
    if route == ("GET", "/pro/user"):
        return JSONResponse({"pro_display_settings": _load(path)})
    if route == ("POST", "/pro/display-settings"):
        settings, error = await _json_body(request, MAX_BYTES, "Settings exceed 1 MB.")
        if error and error.status_code == 413:
            return error
        if not isinstance(settings, dict):  # invalid JSON included
            return JSONResponse({"detail": "The body must be a JSON object."}, status_code=400)
        _save(path, settings)
        return JSONResponse({"pro_display_settings": settings})
    return JSONResponse({"detail": "Method not allowed."}, status_code=405)


def _now():
    """The server's clock, the only updated_date a client compares."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid(raw):
    """A uuid key in one spelling (lowercase, dashed), or None."""
    try:
        return str(uuidlib.UUID(str(raw)))
    except ValueError:
        return None


def _load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path, data):
    """Write atomically: a temp file, then rename over the old one."""
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


async def _json_body(request, limit=MAX_SYNC_BYTES, too_big="The body exceeds 5 MB."):
    """The request body parsed, or (None, a 413/400 response)."""
    body = await request.body()
    if len(body) > limit:
        return None, JSONResponse({"detail": too_big}, status_code=413)
    try:
        return json.loads(body), None
    except ValueError:
        return None, JSONResponse({"detail": "The body must be JSON."}, status_code=400)


def _owned(store, user):
    """Stored dashboards in Workspace's DashboardReturn shape; hidden (system) ones are never listed."""
    return {k: {"creator": True, "content": v["content"], "created_date": v["created_date"],
                "updated_date": v["updated_date"], "created_by": user, "is_shared": False}
            for k, v in store.items() if not v.get("hidden")}


def _ensure_root(store, now):
    """Create the root folder on the first write, adopting every dashboard that names no parent."""
    listed = {k: v for k, v in store.items() if not v.get("hidden")}
    if not listed or any(v["content"].get("isRoot") for v in listed.values()):
        return
    root = str(uuidlib.uuid4())
    children = []
    for key, v in listed.items():
        content = v["content"]
        if not content.get("isFolder") and not content.get("parentId"):
            content["parentId"] = root
            children.append(key)
    store[root] = {"content": {"index": root, "name": "root", "isFolder": True, "isRoot": True,
                               "children": children, "data": {"name": "root"}},
                   "created_date": now, "updated_date": now}


async def _post_dashboards(request, path):
    """POST /pro/dash/sync: {items: {uuid: object | "DELETE"}}, applied per item, never a whole-tree replace."""
    body, error = await _json_body(request)
    if error:
        return error
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, dict):
        return JSONResponse({"detail": "The body must be {items: {uuid: object or DELETE}}."}, status_code=400)
    clean = {}
    for raw, item in items.items():
        key = _uuid(raw)
        if key is None or not (item == "DELETE" or isinstance(item, dict)):
            return JSONResponse({"detail": "Each item must be a JSON object or DELETE under a uuid."}, status_code=400)
        clean[key] = item
    with LOCK:
        store = _load(path)
        now = _now()
        for key, item in clean.items():
            if item == "DELETE":
                store.pop(key, None)
            else:
                store[key] = {"content": item, "created_date": store.get(key, {}).get("created_date", now),
                              "updated_date": now}
        _ensure_root(store, now)
        _save(path, store)
    return JSONResponse({"success": True})


def _owned_apps(store, user):
    """Stored apps in Workspace's UserAppReturn shape (camelCase dates)."""
    return {k: {"content": v["content"], "creator": True, "is_shared": False, "createdDate": v["created_date"],
                "updatedDate": v["updated_date"], "createdBy": user, "sharedWith": []}
            for k, v in store.items()}


async def _app(request, path, raw):
    """POST upserts one app (the body is its content); DELETE removes it, 404 when absent."""
    key = _uuid(raw)
    if key is None:
        return JSONResponse({"detail": "The app id must be a uuid."}, status_code=400)
    if request.method == "DELETE":
        with LOCK:
            apps = _load(path)
            if apps.pop(key, None) is None:
                return JSONResponse({"detail": "No such app."}, status_code=404)
            _save(path, apps)
        return JSONResponse({"success": True})
    body, error = await _json_body(request)
    if error:
        return error
    if not isinstance(body, dict):
        return JSONResponse({"detail": "The body must be a JSON object."}, status_code=400)
    with LOCK:
        apps = _load(path)
        now = _now()
        apps[key] = {"content": body, "created_date": apps.get(key, {}).get("created_date", now), "updated_date": now}
        _save(path, apps)
    return JSONResponse({"success": True})


def _system_record(id_, record, user):
    """One system dashboard as GET/PUT return it: the DashboardReturn fields plus id, hidden and revision."""
    return {"id": id_, "hidden": True, "revision": record["revision"], "creator": True, "content": record["content"],
            "created_date": record["created_date"], "updated_date": record["updated_date"], "created_by": user,
            "is_shared": False}


async def _system(request, path, id_, user):
    """GET, PUT or DELETE the one hidden dashboard a reserved id names; the newest revision wins a PUT."""
    if id_ not in SYSTEM_IDS:
        return JSONResponse({"detail": "No such system dashboard."}, status_code=404)
    if request.method == "GET":
        record = _load(path).get(id_)
        return JSONResponse({"dashboard": _system_record(id_, record, user) if record else None})
    if request.method == "DELETE":
        raw = request.query_params.getlist("revision")
        if len(raw) != 1 or set(request.query_params) != {"revision"} or not raw[0].isascii() \
                or not raw[0].isdigit() or len(raw[0]) > 20:
            return JSONResponse({"detail": "DELETE takes exactly ?revision=<non-negative integer>."}, status_code=400)
        with LOCK:
            store = _load(path)
            stored = store.get(id_)
            if stored and stored["revision"] > int(raw[0]):
                return JSONResponse({"detail": "A newer revision is stored.",
                                     "dashboard": _system_record(id_, stored, user)}, status_code=409)
            if stored is not None:
                del store[id_]
                _save(path, store)
        return JSONResponse({"success": True})
    if request.method != "PUT":
        return JSONResponse({"detail": "Method not allowed."}, status_code=405)
    body, error = await _json_body(request)
    if error:
        return error
    revision = body.get("revision") if isinstance(body, dict) else None
    if (not isinstance(body, dict) or set(body) != {"revision", "content"} or not isinstance(body["content"], dict)
            or type(revision) is not int or revision < 0):
        return JSONResponse({"detail": "The body must be {revision: non-negative integer, content: object}."},
                            status_code=400)
    with LOCK:
        store = _load(path)
        stored = store.get(id_)
        if stored and stored["revision"] > revision:
            return JSONResponse({"detail": "A newer revision is stored.",
                                 "dashboard": _system_record(id_, stored, user)}, status_code=409)
        now = _now()
        record = {"content": body["content"], "created_date": stored["created_date"] if stored else now,
                  "updated_date": now, "hidden": True, "revision": revision}
        store[id_] = record
        _save(path, store)
    return JSONResponse({"success": True, "dashboard": _system_record(id_, record, user)})
