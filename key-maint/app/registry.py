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


def _keyed(var: str, url: str, **params: str | None) -> Callable[[dict[str, str]], httpx.Request | None]:
    """GET url with var's value as the param given as None; no request (None) when var is empty."""
    def build(values: dict[str, str]) -> httpx.Request | None:
        k = _get(values, var)
        if not k:
            return None
        return httpx.Request("GET", url, params={n: k if v is None else v for n, v in params.items()})
    return build


def _alpaca(values: dict[str, str]) -> httpx.Request | None:
    kid, sec = _get(values, "ALPACA_API_KEY"), _get(values, "ALPACA_API_SECRET")
    if not (kid and sec):
        return None
    return httpx.Request(
        "GET",
        "https://data.alpaca.markets/v2/stocks/AAPL/bars/latest",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec},
    )


PROVIDERS: dict[str, Provider] = {
    p.env_var: p
    for p in [
        Provider("FMP", "FMP_API_KEY", "fmp", (), ProbeSpec(
            _keyed("FMP_API_KEY", "https://financialmodelingprep.com/api/v3/profile/AAPL", apikey=None),
            ("Invalid API KEY",))),
        Provider("FRED", "FRED_API_KEY", "fred", (), ProbeSpec(
            _keyed("FRED_API_KEY", "https://api.stlouisfed.org/fred/series",
                   series_id="GNPCA", api_key=None, file_type="json"),
            ("api_key",))),
        Provider("Tiingo", "TIINGO_TOKEN", "tiingo", (), ProbeSpec(
            _keyed("TIINGO_TOKEN", "https://api.tiingo.com/api/test", token=None))),
        # Symbol IBM, not AAPL: the demo key answers only Alpha Vantage's own
        # documented example calls. With AAPL it returns a 200 "demo purposes
        # only" notice that matches no invalid_markers -- a false green.
        Provider("Alpha Vantage", "ALPHA_VANTAGE_API_KEY", "alpha_vantage", ("demo",), ProbeSpec(
            _keyed("ALPHA_VANTAGE_API_KEY", "https://www.alphavantage.co/query",
                   function="GLOBAL_QUOTE", symbol="IBM", apikey=None),
            ("Invalid API call", "apikey"))),
        Provider("Nasdaq Data Link", "NASDAQ_API_KEY", "nasdaq"),
        Provider("EIA", "EIA_API_KEY", "eia", ("DEMO_KEY",), ProbeSpec(
            _keyed("EIA_API_KEY", "https://api.eia.gov/v2/seriesid/STEO.WTIPUUS.M", api_key=None),
            ("API_KEY_MISSING", "invalid api_key"))),
        Provider("BLS", "BLS_API_KEY", "bls", (), ProbeSpec(
            _keyed("BLS_API_KEY", "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
                   registrationkey=None, latest="true"),
            ("REQUEST_NOT_PROCESSED",))),
        Provider("CFTC", "CFTC_APP_TOKEN", "cftc"),
        Provider("Congress.gov", "CONGRESS_GOV_API_KEY", "congress_gov", ("DEMO_KEY",), ProbeSpec(
            _keyed("CONGRESS_GOV_API_KEY", "https://api.congress.gov/v3/bill",
                   limit="1", format="json", api_key=None),
            ("API_KEY_INVALID",))),
        Provider("EconDB", "ECONDB_API_KEY", "econdb"),
        Provider("BizToc", "BIZTOC_API_KEY", "biztoc"),
        # current_usage validates the key (401 on a bad one) and reports usage.
        Provider("Intrinio", "INTRINIO_API_KEY", "intrinio", (), ProbeSpec(
            _keyed("INTRINIO_API_KEY", "https://api-v2.intrinio.com/account/current_usage", api_key=None))),
        Provider("Benzinga", "BENZINGA_API_KEY", "benzinga"),
        Provider("TradingEconomics", "TRADINGECONOMICS_API_KEY", "tradingeconomics"),
        Provider("Tradier", "TRADIER_API_KEY", "tradier"),
        Provider("Alpaca", "ALPACA_API_KEY", "alpaca", (), ProbeSpec(_alpaca)),
        Provider("Alpaca (secret)", "ALPACA_API_SECRET", "alpaca"),
        # /api/user validates the key (401 on a bad one) without spending an API
        # call, and its body carries the day's usage (app.usage).
        Provider("EODHD", "EODHD_API_KEY", "eodhd", ("demo",), ProbeSpec(
            _keyed("EODHD_API_KEY", "https://eodhd.com/api/user", api_token=None, fmt="json"))),
    ]
}

# The API's /providers.json route (lanes/openbq_lanes.py provider_descriptor)
# defines its own _OPTIONAL/_LOCAL mirrors independently -- that route runs in
# the API process and cannot import this package.
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
        "LIVE_GRID_PUBLIC_URL",
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
