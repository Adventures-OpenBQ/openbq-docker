# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The /providers.json descriptor builder, factored out so its classification
(auth optional/required/not_required, local, display name) has a unit test
without building the image. The Dockerfile inlines a byte-identical copy of
build_provider_descriptor into openbb_core's rest_api.py patch (that route
runs in the API process and cannot import this package); keep the two in sync.
Names only -- no credential value is read, so none can leak."""
from __future__ import annotations

_OPTIONAL = frozenset({"cftc", "econdb"})           # bls is key-required (54354a9)
_LOCAL = frozenset({"deltalake", "kdb"})            # neither ships at v3; key stays in the contract
_NAMES = {
    "yfinance": "Yahoo Finance", "sec": "SEC", "federal_reserve": "Federal Reserve",
    "imf": "IMF", "oecd": "OECD", "government_us": "US Government", "fmp": "FMP",
    "fred": "FRED", "tiingo": "Tiingo", "eia": "EIA", "bls": "BLS", "cftc": "CFTC",
    "congress_gov": "Congress.gov", "econdb": "EconDB", "intrinio": "Intrinio",
    "benzinga": "Benzinga", "tradingeconomics": "TradingEconomics", "eodhd": "EODHD",
    "deltalake": "Delta Lake", "kdb": "kdb+",
}

def build_provider_descriptor(credentials: dict[str, list[str]]) -> list:
    out = []
    for pid in sorted(credentials):
        names = list(credentials[pid])
        if names:
            auth = "optional" if pid in _OPTIONAL else "required"
        else:
            auth = "not_required"
        out.append({
            "id": pid,
            "name": _NAMES.get(pid, pid.replace("_", " ").title()),
            "credentials": names,
            "env_vars": [c.upper() for c in names],
            "auth": auth,
            "local": pid in _LOCAL,
        })
    return out
