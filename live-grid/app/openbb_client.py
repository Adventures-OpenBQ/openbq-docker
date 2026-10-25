# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Client for the OpenBB API on loopback.

Going through the real API (rather than importing the provider) means the demo
exercises exactly the path any other client takes -- including the cache
metadata the Platform attaches to every response.
"""

import os

OPENBB_URL = os.getenv("OPENBB_URL", "http://127.0.0.1:6900")
USERNAME = os.getenv("OPENBB_API_USERNAME", "")
PASSWORD = os.getenv("OPENBB_API_PASSWORD", "")

_UNKNOWN = {
    "cache": "unknown", "rows_from_cache": 0, "rows_from_upstream": 0,
    "gaps_fetched": 0, "upstream_ms": 0.0, "kdb_ms": 0.0,
}

# Same shape rules the live feeds use (classify.py). Routing everything
# through equity/price/historical sent BTC-USD upstream as BTC-USD.US,
# which EODHD 404s -- each asset class has its own Platform route, and the
# kdb provider registers a fetcher for all three.
_HISTORICAL_PATH = {
    "us": "equity/price/historical",
    "crypto": "crypto/price/historical",
    "forex": "currency/price/historical",
}


def history_endpoint(symbol: str) -> str:
    """The Platform route for this symbol's asset class."""
    from app.classify import classify

    return _HISTORICAL_PATH[classify(symbol)]


# openbq-docker v10 (PROVISIONAL, docs/v10/live-grid-kdb-port.md). openbq-api installs no
# standard routers and no openbb-kdb provider, so `equity/price/historical?provider=kdb`
# does not exist there. EODHD is served by its own namespace instead (obb.eodhd.*,
# /api/v1/eodhd/<class>/price/historical, provider `eodhd` only). OPENBB_HISTORY_NAMESPACE
# names that namespace; when it is set, every history fetch goes to it and asks for the
# namespace's own provider, whatever `provider` the route was given. Unset (the donor's
# behaviour, and the default) changes nothing. Read per call, not at import.
def history_namespace() -> str:
    """The extension namespace history is served from, or "" for the standard routes."""
    return os.getenv("OPENBB_HISTORY_NAMESPACE", "").strip().strip("/")


# Futures (CL=F) have no EODHD route; openbq-yfinance serves them on its own namespace,
# whatever OPENBB_HISTORY_NAMESPACE says.
_FUTURES_ROUTE = ("yfinance/futures/historical", "yfinance")


def history_route(symbol: str, provider: str) -> tuple[str, str]:
    """(route under /api/v1/, provider) for one history fetch."""
    from app.classify import classify

    if classify(symbol) == "futures":
        return _FUTURES_ROUTE
    namespace = history_namespace()
    if namespace:
        return f"{namespace}/{history_endpoint(symbol)}", namespace
    return history_endpoint(symbol), provider


async def fetch_series(
    symbol: str, interval: str, start: str, end: str, provider: str = "kdb"
) -> tuple[list[dict], dict]:
    """Return (bars, cache_metadata) for one window."""
    import httpx

    route, provider = history_route(symbol, provider)
    params = {
        "symbol": symbol, "provider": provider, "interval": interval,
        "start_date": start, "end_date": end,
    }
    auth = (USERNAME, PASSWORD) if USERNAME else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{OPENBB_URL}/api/v1/{route}", params=params, auth=auth
        )
        response.raise_for_status()
        payload = response.json()
    bars = payload.get("results") or []
    meta = (payload.get("extra") or {}).get("results_metadata") or dict(_UNKNOWN)
    return bars, meta
