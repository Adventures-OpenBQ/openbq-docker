# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

"""A vendor's API usage, read from a successful credential-probe response.

Informational only: it never decides a check's result. Every missing,
non-numeric or negative value yields None rather than a guess, and
parse_usage never raises -- a vendor changing its usage format must not
break the credential check that carries it."""
from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta

import httpx

# Providers whose existing probe answers with x-ratelimit-* headers, and the
# window those headers count. Only these are parsed.
HEADER_WINDOWS: dict[str, str] = {"eia": "hour", "alpaca": "minute"}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v) -> int | None:
    """A non-negative whole count from a number or numeric string, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or v < 0:
        return None
    return int(v)


def _usage(used, limit, window, resets_at=None, extra=None) -> dict | None:
    if used is None or not limit:  # limit None or 0: no allowance to report against
        return None
    u = {"used": used, "limit": limit, "window": window}
    if resets_at is not None:
        u["resets_at"] = resets_at
    if extra is not None:
        u["extra"] = extra
    return u


def _body(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        return None


def _eodhd(resp: httpx.Response, now: datetime) -> dict | None:
    body = _body(resp)
    if not isinstance(body, dict):
        return None
    day = body.get("apiRequestsDate")
    if not isinstance(day, str):
        return None
    # The counter only resets on the first request after midnight GMT, so a
    # date that is not today means nothing has been spent today yet.
    used = _num(body.get("apiRequests")) if day == now.date().isoformat() else 0
    midnight = datetime.combine(now.date() + timedelta(days=1), time(), UTC)
    return _usage(used, _num(body.get("dailyRateLimit")), "day",
                  _iso(midnight), _num(body.get("extraLimit")))


def _intrinio(resp: httpx.Response, now: datetime) -> dict | None:
    body = _body(resp)
    # ponytail: response envelope unverified (docs: "a list of access codes");
    # accepts a bare list or the first list inside an object. Pin it once a
    # live key shows the real shape.
    if isinstance(body, dict):
        body = next((v for v in body.values() if isinstance(v, list)), None)
    if not isinstance(body, list):
        return None
    best = None
    for e in body:
        if not isinstance(e, dict):
            continue
        count, limit = _num(e.get("count")), _num(e.get("limit"))
        if count is None or not limit:
            continue
        # count/limit is percentage_used without trusting a third field.
        if best is None or count / limit > best[0] / best[1]:
            best = (count, limit, _num(e.get("seconds_until_reset")))
    if best is None:
        return None
    count, limit, secs = best
    resets = _iso(now + timedelta(seconds=secs)) if secs is not None else None
    return _usage(count, limit, "period", resets)


def _headers(resp: httpx.Response, window: str) -> dict | None:
    limit = _num(resp.headers.get("x-ratelimit-limit"))
    remaining = _num(resp.headers.get("x-ratelimit-remaining"))
    if limit is None or remaining is None or remaining > limit:
        return None
    reset = _num(resp.headers.get("x-ratelimit-reset"))
    # Only an epoch timestamp is a reset time; a small number would be a
    # seconds-until value from some other convention, so it is ignored.
    resets = _iso(datetime.fromtimestamp(reset, UTC)) if reset and reset > 1_000_000_000 else None
    return _usage(limit - remaining, limit, window, resets)


def parse_usage(provider_id: str, resp: httpx.Response, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(UTC)
    try:
        if provider_id == "eodhd":
            return _eodhd(resp, now)
        if provider_id == "intrinio":
            return _intrinio(resp, now)
        window = HEADER_WINDOWS.get(provider_id)
        return _headers(resp, window) if window else None
    except Exception:  # noqa: BLE001 -- never let usage parsing break a credential check
        return None
