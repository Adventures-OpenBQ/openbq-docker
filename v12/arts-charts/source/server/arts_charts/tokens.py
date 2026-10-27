# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Signed, expiring tokens: one HMAC-SHA256 secret (ARTS_CHARTS_SECRET), no token table.

A token is `<claims>.<signature>`, both base64url without padding. The claims
are JSON with `scope` and `exp` (Unix seconds) beside the scope's own:

  wake    {by, charts}      a headless Rita turn (chart_tools.caller)
  action  {watch, action}   an ntfy button (POST /watches/action)
  worker  {}                the worker's inbox writes (POST /inbox)
  link    {item}            GET of one inbox item and its PNGs (an ntfy click/attachment)

Stateless by design (overnight decision 10): a token is good until it
expires, so whatever it allows must be safe to do twice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenError(ValueError):
    """Why a token is refused: not set up, forged, expired or of another scope."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _mac(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def sign(secret: str, scope: str, ttl: float, now: float | None = None, **claims) -> str:
    """A token of `scope` carrying `claims`, valid for `ttl` seconds from `now`."""
    exp = int((time.time() if now is None else now) + ttl)
    body = _b64(json.dumps({**claims, "scope": scope, "exp": exp},
                           separators=(",", ":")).encode())
    return f"{body}.{_mac(secret, body)}"


def verify(secret: str | None, token: str, scope: str, now: float | None = None) -> dict:
    """The claims of a good, unexpired `scope` token; TokenError otherwise."""
    if not secret:
        raise TokenError("ARTS_CHARTS_SECRET is not set")
    body, _, signature = token.partition(".")
    if not hmac.compare_digest(signature.encode(), _mac(secret, body).encode()):
        raise TokenError("bad token")
    try:
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        raise TokenError("bad token") from None
    if not isinstance(claims, dict) or claims.get("scope") != scope:
        raise TokenError(f"not a {scope} token")
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= (time.time() if now is None else now):
        raise TokenError("token expired")
    return claims
