# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Static map of provider credentials: display names, public demo values,
and the cheapest authenticated probe request per provider.

Probes build an httpx.Request from the FULL parsed credentials dict so
multi-var providers (Alpaca key+secret) work. A provider with probe=None is
reported as test 'skipped'. invalid_markers are substrings of a 2xx body that
mean the key was rejected anyway (providers that never 401)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx


@dataclass(frozen=True)
class ProbeSpec:
    build: Callable[[dict[str, str]], httpx.Request | None]
    invalid_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Provider:
    name: str
    env_var: str
    provider_id: str
    demo_values: tuple[str, ...] = ()
    probe: ProbeSpec | None = None


def _get(values: dict[str, str], var: str) -> str | None:
    v = values.get(var, "").strip()
    return v or None


def _eodhd(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "EODHD_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET",
        "https://eodhd.com/api/eod/AAPL.US",
        params={"api_token": k, "fmt": "json", "period": "d", "order": "d", "limit": 1},
    )


def _fmp(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "FMP_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET", "https://financialmodelingprep.com/api/v3/profile/AAPL", params={"apikey": k}
    )


def _fred(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "FRED_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET",
        "https://api.stlouisfed.org/fred/series",
        params={"series_id": "GNPCA", "api_key": k, "file_type": "json"},
    )


def _tiingo(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "TIINGO_TOKEN")
    if not k:
        return None
    return httpx.Request("GET", "https://api.tiingo.com/api/test", params={"token": k})


def _bls(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "BLS_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET",
        "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
        params={"registrationkey": k, "latest": "true"},
    )


def _eia(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "EIA_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET", "https://api.eia.gov/v2/seriesid/STEO.WTIPUUS.M", params={"api_key": k}
    )


def _intrinio(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "INTRINIO_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET", "https://api-v2.intrinio.com/companies/AAPL", params={"api_key": k}
    )


def _alpaca(values: dict[str, str]) -> httpx.Request | None:
    kid, sec = _get(values, "ALPACA_API_KEY"), _get(values, "ALPACA_API_SECRET")
    if not (kid and sec):
        return None
    return httpx.Request(
        "GET",
        "https://data.alpaca.markets/v2/stocks/AAPL/bars/latest",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec},
    )


def _congress(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "CONGRESS_GOV_API_KEY")
    if not k:
        return None
    return httpx.Request(
        "GET",
        "https://api.congress.gov/v3/bill",
        params={"limit": "1", "format": "json", "api_key": k},
    )


def _alpha_vantage(values: dict[str, str]) -> httpx.Request | None:
    k = _get(values, "ALPHA_VANTAGE_API_KEY")
    if not k:
        return None
    # Symbol IBM, not AAPL: the demo key answers only Alpha Vantage's own
    # documented example calls. With AAPL it returns a 200 "demo purposes
    # only" notice that matches no invalid_markers -- a false green.
    return httpx.Request(
        "GET",
        "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": k},
    )


def _p(name, env_var, provider_id, demo=(), probe=None):
    return Provider(name=name, env_var=env_var, provider_id=provider_id,
                    demo_values=demo, probe=probe)


PROVIDERS: dict[str, Provider] = {
    p.env_var: p
    for p in [
        _p("FMP", "FMP_API_KEY", "fmp", (), ProbeSpec(_fmp, ("Invalid API KEY",))),
        _p("FRED", "FRED_API_KEY", "fred", (), ProbeSpec(_fred, ("api_key",))),
        _p("Tiingo", "TIINGO_TOKEN", "tiingo", (), ProbeSpec(_tiingo)),
        _p(
            "Alpha Vantage",
            "ALPHA_VANTAGE_API_KEY",
            "alpha_vantage",
            ("demo",),
            ProbeSpec(_alpha_vantage, ("Invalid API call", "apikey")),
        ),
        _p("Nasdaq Data Link", "NASDAQ_API_KEY", "nasdaq"),
        _p("EIA", "EIA_API_KEY", "eia", ("DEMO_KEY",), ProbeSpec(_eia, ("API_KEY_MISSING", "invalid api_key"))),
        _p("BLS", "BLS_API_KEY", "bls", (), ProbeSpec(_bls, ("REQUEST_NOT_PROCESSED",))),
        _p("CFTC", "CFTC_APP_TOKEN", "cftc"),
        _p(
            "Congress.gov",
            "CONGRESS_GOV_API_KEY",
            "congress_gov",
            ("DEMO_KEY",),
            ProbeSpec(_congress, ("API_KEY_INVALID",)),
        ),
        _p("EconDB", "ECONDB_API_KEY", "econdb"),
        _p("BizToc", "BIZTOC_API_KEY", "biztoc"),
        _p("Intrinio", "INTRINIO_API_KEY", "intrinio", (), ProbeSpec(_intrinio)),
        _p("Benzinga", "BENZINGA_API_KEY", "benzinga"),
        _p("TradingEconomics", "TRADINGECONOMICS_API_KEY", "tradingeconomics"),
        _p("Tradier", "TRADIER_API_KEY", "tradier"),
        _p("Alpaca", "ALPACA_API_KEY", "alpaca", (), ProbeSpec(_alpaca)),
        _p("Alpaca (secret)", "ALPACA_API_SECRET", "alpaca"),
        _p("EODHD", "EODHD_API_KEY", "eodhd", ("demo",), ProbeSpec(_eodhd)),
    ]
}

# The Dockerfile-inlined /providers.json route (key-maint/app/providers_route.py
# is its unit-tested twin) defines its own _OPTIONAL/_LOCAL mirrors independently --
# that route runs in the API process and cannot import this package.
#
# bls is NOT here: an isolated stack run showed the real platform 400s
# "Missing credential" for bls without a key, while cftc/econdb answer keyless
# -- the API's credential gate, not the fetcher, decides optionality.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"deltalake", "kdb"})
OPTIONAL_PROVIDERS: frozenset[str] = frozenset({"cftc", "econdb"})


def provider_index() -> dict[str, Provider]:
    """Providers keyed by OpenBB provider_id. ALPACA_API_KEY/_SECRET share the
    'alpaca' id; the first PROVIDERS entry with a given id wins (the primary
    credential var), which is the one rows.py joins the descriptor against."""
    idx: dict[str, Provider] = {}
    for p in PROVIDERS.values():
        idx.setdefault(p.provider_id, p)
    return idx


# Non-credential configuration vars that legitimately live in credentials.env.
IGNORE: frozenset[str] = frozenset(
    {
        "TRADIER_ACCOUNT_TYPE",
        "KDB_CONTAINER",
        "KDB_HOST",
        "S3_CONTAINER",
        "ARCTICDB_BUCKET",
        "ARCTICDB_LIBRARY",
        "ARCTICDB_URI",
        # OpenBQ's credentials.env also carries the API's own Basic auth (which
        # key-maint follows, never reports) and SEC's contact user agent.
        "OPENBB_API_AUTH",
        "OPENBB_API_USERNAME",
        "OPENBB_API_PASSWORD",
        "SEC_USER_AGENT",
    }
)


def is_demo(env_var: str, value: str) -> bool:
    p = PROVIDERS.get(env_var)
    if p is None or not value:
        return False
    return value.lower() in {d.lower() for d in p.demo_values}
