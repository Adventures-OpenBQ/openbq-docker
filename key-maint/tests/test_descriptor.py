# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only
import asyncio

import httpx

from app.descriptor import fetch_descriptor

SAMPLE = [
    {"id": "yfinance", "name": "Yahoo Finance", "credentials": [], "env_vars": [],
     "auth": "not_required", "local": False},
    {"id": "fmp", "name": "FMP", "credentials": ["fmp_api_key"], "env_vars": ["FMP_API_KEY"],
     "auth": "required", "local": False},
]


def _run(handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_descriptor("http://openbb-api:6900", "u", "p", client=c)
    return asyncio.run(go())


def test_parses_a_2xx_list():
    result = _run(lambda r: httpx.Response(200, json=SAMPLE))
    assert result == SAMPLE


def test_sends_basic_auth():
    seen = {}

    def handler(r):
        seen["auth"] = r.headers.get("authorization")
        return httpx.Response(200, json=SAMPLE)

    _run(handler)
    assert seen["auth"] and seen["auth"].startswith("Basic ")


def test_non_2xx_returns_none():
    assert _run(lambda r: httpx.Response(500)) is None


def test_fetch_failure_returns_none():
    def boom(r):
        raise httpx.ConnectError("nope", request=r)
    assert _run(boom) is None


def test_non_list_body_returns_none():
    assert _run(lambda r: httpx.Response(200, json={"not": "a list"})) is None
