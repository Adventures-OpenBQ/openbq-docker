# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""One stored example request per non-local provider. It is both the
connectivity probe's source and a release check: `python -m app.catalog
--check <OPENBB_URL>` runs every example and fails when a vendor call has
drifted. The classifier is shared with scripts/smoke.sh so the shell step and
the running service agree. Detail strings are built ONLY from fixed sentences
and status codes — the OpenBB API's raw `detail` is parsed for markers but
never forwarded (it can carry a vendor URL or key material)."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_D = "https://docs.openbb.co/platform/reference"


@dataclass(frozen=True)
class Example:
    provider_id: str
    path: str
    params: dict[str, str]
    demo_ok: bool
    doc: str


def _ex(pid, path, params, doc, demo_ok=False):
    return Example(pid, path, {"provider": pid, **params}, demo_ok, doc)


# Paths follow OpenBQ's API, which routes most installed providers under their
# own id (/api/v1/fred/..., /api/v1/sec/...). Providers OpenBQ does not install
# keep their OpenBB paths; key-maint marks them "not installed" and never calls.
EXAMPLES: dict[str, Example] = {e.provider_id: e for e in [
    _ex("yfinance", "/api/v1/yfinance/equity/quote", {"symbol": "AAPL"},
        f"{_D}/equity/price/quote", demo_ok=True),
    _ex("sec", "/api/v1/sec/company_filings", {"symbol": "AAPL", "limit": "1"},
        f"{_D}/equity/fundamental/filings", demo_ok=True),
    _ex("federal_reserve", "/api/v1/federal_reserve/money_measures", {},
        f"{_D}/economy/money_measures", demo_ok=True),
    _ex("imf", "/api/v1/imf/available_indicators", {"query": "GDP"},
        f"{_D}/economy/available_indicators", demo_ok=True),
    _ex("oecd", "/api/v1/oecd/gdp_real", {"country": "united_states"},
        f"{_D}/economy/gdp/real", demo_ok=True),
    _ex("government_us", "/api/v1/fixedincome/government/treasury_auctions", {},
        f"{_D}/fixedincome/government/treasury_auctions", demo_ok=True),
    _ex("eodhd", "/api/v1/equity/price/quote", {"symbol": "AAPL"},
        f"{_D}/equity/price/quote", demo_ok=True),
    _ex("fmp", "/api/v1/equity/profile", {"symbol": "AAPL"}, f"{_D}/equity/profile"),
    _ex("fred", "/api/v1/fred/economy/fred_series", {"symbol": "GNPCA"}, f"{_D}/economy/fred_series"),
    _ex("tiingo", "/api/v1/equity/price/historical", {"symbol": "AAPL"},
        f"{_D}/equity/price/historical"),
    _ex("intrinio", "/api/v1/equity/profile", {"symbol": "AAPL"}, f"{_D}/equity/profile"),
    _ex("eia", "/api/v1/eia/short_term_energy_outlook", {},
        f"{_D}/commodity/short_term_energy_outlook", demo_ok=True),
    _ex("congress_gov", "/api/v1/uscongress/bills", {"limit": "1"},
        f"{_D}/uscongress/bills", demo_ok=True),
    # bls is keyed, not demo-capable: the platform 400s "Missing credential"
    # for it without a key (verified against an isolated stack run), unlike
    # cftc/econdb below which answer keyless.
    _ex("bls", "/api/v1/bls/series", {"symbol": "CUUR0000SA0"},
        f"{_D}/economy/survey/bls_series"),
    _ex("cftc", "/api/v1/cftc/cot", {"code": "CFTC_088691"}, f"{_D}/cftc/cot", demo_ok=True),
    _ex("econdb", "/api/v1/economy/country_profile", {"country": "us"},
        f"{_D}/economy/country_profile", demo_ok=True),
    _ex("benzinga", "/api/v1/news/company", {"symbol": "AAPL", "limit": "1"},
        f"{_D}/news/company"),
    _ex("tradingeconomics", "/api/v1/economy/calendar", {},
        f"{_D}/economy/calendar"),
]}

# egress_policy_denied is RESERVED (spec §4): a firewall/egress denial is a
# claim key-maint cannot substantiate from an API error string alone — nothing
# here can supply the affirmative evidence — so this classifier never emits it.
_DETAIL = {
    "http_auth": "the provider rejected the credential",
    "rate_limited": "the provider rate-limited the request",
    "upstream_error": "the provider returned an error",
    "unexpected_response": "the response did not contain the expected data",
    "connect_timeout": "the provider did not respond in time",
    "dns_failure": "the provider host could not be resolved",
    "connect_refused": "the provider refused the connection",
    "tls_error": "the provider's TLS certificate could not be verified",
}
_BACKEND_REFUSED = "the backend refused key-maint's own credentials"


def _marker_code(detail_text: str) -> tuple[str, str]:
    """(result, code) from markers in the API's own detail string. The text is
    read for signal only; it is NEVER placed in the returned detail."""
    t = detail_text
    tl = t.lower()
    if "timed out" in tl or "timeout" in tl:
        return "no_response", "connect_timeout"
    if "Name or service not known" in t or "NameResolutionError" in t or "nodename" in tl:
        return "no_response", "dns_failure"
    if "connection refused" in tl:
        return "no_response", "connect_refused"
    if "ssl" in tl or "certificate" in tl:
        return "no_response", "tls_error"
    if any(m in t for m in ("401", "403")) or any(
        m in tl for m in ("unauthorized", "forbidden", "invalid api", "missing credential")
    ):
        return "auth_failed", "http_auth"
    if "429" in t or "rate limit" in tl:
        return "error", "rate_limited"
    return "error", "upstream_error"


def classify(status: int, body) -> tuple[str, str | None, str]:
    """(result, code, detail) for an API response that WAS received. Transport
    failures that never reached the API are handled by the connectivity probe."""
    if 200 <= status < 300:
        if isinstance(body, dict) and body.get("results"):
            return "ok", None, f"HTTP {status}"
        return "error", "unexpected_response", f"{_DETAIL['unexpected_response']} (HTTP {status})"
    if status in (401, 403):
        return "error", "http_auth", _BACKEND_REFUSED
    detail_text = ""
    if isinstance(body, dict):
        detail_text = str(body.get("detail", ""))
    result, code = _marker_code(detail_text)
    return result, code, f"{_DETAIL[code]} (HTTP {status})"


def _check(base_url: str, username: str, password: str) -> int:
    """Run every example through the API and enforce the demo policy:
    demo_ok -> must be ok; keyed (others) -> ok, auth_failed, or skipped are
    all acceptable, since a keyed example run against a deployment WITH real
    keys legitimately comes back ok (that is not drift -- fmp/fred/bls/
    benzinga all did exactly that on 2026-09-24 against production). Any
    no_response/unexpected_response/upstream_error is drift and fails. Returns
    a process exit code."""
    ok_others = {"ok", "auth_failed", "skipped"}
    failures: list[str] = []
    with httpx.Client(timeout=15.0) as client:
        for pid, ex in EXAMPLES.items():
            try:
                resp = client.get(f"{base_url.rstrip('/')}{ex.path}",
                                  params=ex.params, auth=(username, password))
                body = resp.json() if resp.headers.get("content-type", "").startswith(
                    "application/json") else {}
                result, _, _ = classify(resp.status_code, body)
            except httpx.HTTPError as e:
                result = "no_response"
                print(f"{pid}: transport error {type(e).__name__}")
            want_ok = ex.demo_ok
            passed = (result == "ok") if want_ok else (result in ok_others)
            print(f"{pid:<18} {result:<14} {'demo_ok' if want_ok else 'keyed'} "
                  f"-> {'PASS' if passed else 'FAIL'}")
            if not passed:
                failures.append(pid)
    if failures:
        print(f"catalog drift: {', '.join(failures)}")
        return 1
    print("catalog OK")
    return 0


def main(argv=None) -> int:
    import argparse
    import os

    from app.credfile import load
    parser = argparse.ArgumentParser(prog="app.catalog")
    parser.add_argument("--check", metavar="OPENBB_URL", required=True)
    args = parser.parse_args(argv)
    auth = load(os.environ.get("KEYMAINT_AUTH_FILE", "/config/credentials.env")) or {}
    return _check(args.check, auth.get("OPENBB_API_USERNAME", ""),
                  auth.get("OPENBB_API_PASSWORD", ""))


if __name__ == "__main__":
    raise SystemExit(main())
