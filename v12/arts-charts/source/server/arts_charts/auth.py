# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The stack's shared OpenBB API pair, enforced on every arts-charts route and presented
to everything arts-charts calls with it.

In the openbq stack trust is the Basic pair from `credentials.env` --
OPENBB_API_AUTH, OPENBB_API_USERNAME, OPENBB_API_PASSWORD -- not network membership.
The pattern is live-grid's (openbq-docker/live-grid/app/auth.py), reimplemented here:
a RAW ASGI middleware, so websockets and the SSE feed are covered as well as plain HTTP;
fails CLOSED when either half of the pair is empty; constant-time compare; a websocket is
refused with close 1008 before accept; a 401 carries `WWW-Authenticate: Basic`.

Enabled only when OPENBB_API_AUTH is truthy (everywhere else, tests included, it is off).
The routes read OPENBB_API_USERNAME / _PASSWORD only: ARTS_CHARTS_ODP_USER / _PASSWORD
override the pair arts-charts presents to ODP, never the one it demands.

One route is exempt, `POST /watches/action` -- an ntfy button, which cannot hold the pair
and carries its own signed, single-watch, single-action token instead.

Two GETs are open to a per-item `link` token in `?t=`: `/inbox/<id>` and
`/inbox/<id>/snapshots/<n>.png`, the click and attachment URLs of an ntfy push. The token
is signed for that one item (tokens.py), so it opens nothing else; the handlers never see it.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import secrets
from urllib.parse import parse_qsl

import httpx
from starlette.routing import get_route_path

from arts_charts.tokens import TokenError, verify

_TRUE = ("1", "true", "yes", "on")
#: (method, exact path) pairs that carry their own credential. Nothing else.
EXEMPT = frozenset({("POST", "/watches/action")})


#: The two paths a link token may open; group 1 is the item the token must name.
_LINK_PATH = re.compile(r"/inbox/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
                        r"(?:/snapshots/[0-9]{1,6}\.png)?")


def link_ok(scope) -> bool:
    """True for a GET of one inbox item (or its PNG) carrying a good, unexpired `link`
    token for that same item in the first `t` query value."""
    if scope["method"] != "GET":
        return False
    found = _LINK_PATH.fullmatch(get_route_path(scope))
    token = next((v for k, v in parse_qsl(scope.get("query_string", b"").decode("latin-1"),
                                           keep_blank_values=True) if k == "t"), None)
    if not found or token is None:
        return False
    try:
        return verify(os.environ.get("ARTS_CHARTS_SECRET"), token, "link").get("item") == found[1]
    except TokenError:
        return False


def auth_enabled() -> bool:
    return os.environ.get("OPENBB_API_AUTH", "").strip().lower() in _TRUE


def _pair() -> tuple[str, str]:
    return os.environ.get("OPENBB_API_USERNAME", ""), os.environ.get("OPENBB_API_PASSWORD", "")


def credentials_ok(header: str | None) -> bool:
    """True when `header` carries the configured Basic pair."""
    username, password = _pair()
    supplied_user = supplied_pw = ""
    if header and header[:6].lower() == "basic ":
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded = ""
        if ":" in decoded:
            supplied_user, _, supplied_pw = decoded.partition(":")
    ok_user = secrets.compare_digest(supplied_user.encode(), username.encode())
    ok_pw = secrets.compare_digest(supplied_pw.encode(), password.encode())
    # `username and password` fails closed: compare_digest("", "") is true, and
    # `Basic <base64 of ":">` would otherwise open an unconfigured pair.
    return bool(username and password and ok_user and ok_pw)


class BasicAuthMiddleware:
    """Refuse unauthenticated HTTP requests and websocket connections."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not auth_enabled():
            await self.app(scope, receive, send)
            return
        # The decoded path the router matches on (root_path stripped): only the exact
        # string is exempt, so a trailing slash, `..`, a doubled slash or another method
        # is refused here.
        if scope["type"] == "http" and (scope["method"], get_route_path(scope)) in EXEMPT:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and link_ok(scope):
            await self.app(scope, receive, send)
            return
        header = next((v.decode("latin-1") for k, v in scope.get("headers") or []
                       if k == b"authorization"), None)
        if credentials_ok(header):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})  # before accept
        else:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"www-authenticate", b"Basic"), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})


class StackAuth(httpx.Auth):
    """For every client that calls arts-charts' own API (the worker, the in-process tools
    and renderer): the pair, when the stack has auth on. Read per request, like the
    middleware."""

    def auth_flow(self, request):
        if auth_enabled():
            user, password = _pair()
            request.headers["Authorization"] = "Basic " + base64.b64encode(
                f"{user}:{password}".encode()).decode()
        yield request


def odp_credentials(env) -> tuple[str, str] | None:
    """The Basic pair for ODP: ARTS_CHARTS_ODP_USER/_PASSWORD when the user is set,
    otherwise the stack's OPENBB_API_USERNAME/_PASSWORD; None when neither names a user.
    SystemExit when a user has no password."""
    for user_key, password_key in (("ARTS_CHARTS_ODP_USER", "ARTS_CHARTS_ODP_PASSWORD"),
                                   ("OPENBB_API_USERNAME", "OPENBB_API_PASSWORD")):
        user = env.get(user_key)
        if user:
            password = env.get(password_key)
            if not password:
                raise SystemExit(f"{user_key} needs {password_key}")
            return user, password
    return None


class _RedactToken(logging.Filter):
    """uvicorn's access log prints the request line; a link token in it is a 7-day
    credential for one item, so its value never reaches a log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(re.sub(r"([?&]t=)[^&\s]*", r"\1REDACTED", a)
                                if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactToken())
