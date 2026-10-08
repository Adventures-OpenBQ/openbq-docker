# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""BDOBB key-mode user settings: GET /pro/user and POST /pro/display-settings.

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
from pathlib import Path

from starlette.responses import JSONResponse

STORE = Path(os.environ.get("OPENBQ_SETTINGS_DIR", "/root/OpenBBUserData/bdobb-settings"))
MAX_BYTES = 1_000_000
PATHS = {"/pro/user", "/pro/display-settings"}


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
    """Serve the two settings routes; pass every other request (and preflight) through."""
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
    path = STORE / f"{hashlib.sha256(credential.encode()).hexdigest()}.json"
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
