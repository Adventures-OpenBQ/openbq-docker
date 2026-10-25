# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Fetch the live provider inventory from the OpenBB API's /providers.json.

The route is read live from the platform (no hand-copied table). Any failure
returns None — /keys then falls back to registry-only rows — and logs ONE line
naming only the status code or exception class, never a URL or body."""
from __future__ import annotations

import logging

import httpx

TIMEOUT_S = 5.0
_log = logging.getLogger("app.descriptor")


async def fetch_descriptor(
    base_url: str,
    username: str,
    password: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict] | None:
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        resp = await client.get(
            f"{base_url.rstrip('/')}/providers.json",
            auth=(username, password),
        )
    except httpx.HTTPError as e:
        _log.warning("descriptor fetch failed: %s", type(e).__name__)
        return None
    finally:
        if own:
            await client.aclose()
    if not resp.is_success:
        _log.warning("descriptor fetch: HTTP %s", resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError:
        _log.warning("descriptor fetch: non-JSON body")
        return None
    if not isinstance(body, list):
        _log.warning("descriptor fetch: body was not a list")
        return None
    return body
