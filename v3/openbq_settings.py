# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""BDOBB key-mode user settings, dashboards and apps.

Settings: GET /pro/user and POST /pro/display-settings. Dashboards and apps: the
subset of OpenBB Workspace's own sync routes BDOBB speaks (GET /pro/dash/sync/owned,
GET /pro/dash/sync/shared, POST /pro/dash/sync, GET /pro/user-apps/sync,
POST and DELETE /pro/user-apps/{uuid}).

Authorised by the API's own Basic credential (OPENBB_API_AUTH with
OPENBB_API_USERNAME and OPENBB_API_PASSWORD). With API auth off there is no key
to check, so both routes answer 404, as on a backend without a settings API.
One JSON object per credential, replaced wholesale on POST and kept as sent
(unknown keys included), on the persistent user-data volume.
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
         "/pro/dash/sync/shared"}
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

    if request.url.path not in PATHS or request.method == "OPTIONS" or not Env().API_AUTH:
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
    path = STORE / f"{key}.json"
    if (request.method, request.url.path) == ("GET", "/pro/user"):
        settings = json.loads(path.read_text()) if path.exists() else {}
        return JSONResponse({"pro_display_settings": settings})
    if (request.method, request.url.path) == ("POST", "/pro/display-settings"):
        body = await request.body()
        if len(body) > MAX_BYTES:
            return JSONResponse({"detail": "Settings exceed 1 MB."}, status_code=413)
        try:
            settings = json.loads(body)
        except ValueError:
            settings = None
        if not isinstance(settings, dict):
            return JSONResponse({"detail": "The body must be a JSON object."}, status_code=400)
        STORE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(settings))
        os.replace(tmp, path)
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


async def _json_body(request):
    """The request body parsed, or (None, a 413/400 response)."""
    body = await request.body()
    if len(body) > MAX_SYNC_BYTES:
        return None, JSONResponse({"detail": "The body exceeds 5 MB."}, status_code=413)
    try:
        return json.loads(body), None
    except ValueError:
        return None, JSONResponse({"detail": "The body must be JSON."}, status_code=400)


def _owned(store, user):
    """Stored dashboards in Workspace's DashboardReturn shape."""
    return {k: {"creator": True, "content": v["content"], "created_date": v["created_date"],
                "updated_date": v["updated_date"], "created_by": user, "is_shared": False}
            for k, v in store.items()}


def _ensure_root(store, now):
    """Create the root folder on the first write, adopting every dashboard that names no parent."""
    if not store or any(v["content"].get("isRoot") for v in store.values()):
        return
    root = str(uuidlib.uuid4())
    children = []
    for v in store.values():
        content = v["content"]
        if not content.get("isFolder") and not content.get("parentId"):
            content["parentId"] = root
            children.append(content.get("index"))
    store[root] = {"content": {"index": root, "name": "root", "isFolder": True, "isRoot": True,
                               "children": [c for c in children if c], "data": {"name": "root"}},
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
