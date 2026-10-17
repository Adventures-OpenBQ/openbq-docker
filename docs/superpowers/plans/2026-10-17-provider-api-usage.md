# Provider API Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a provider key is tested, key-maint reports the vendor's API usage (calls used / allowance / window) for EODHD, Intrinio, EIA and Alpaca, and the bdobb Keys dashboard and Details dialog show it.

**Architecture:** A new pure parser module in key-maint (`app/usage.py`) turns a successful credential-probe response into an optional `usage` dict; `Check` carries it and `_check_dict` serialises it. EODHD and Intrinio credential probes move to their free usage endpoints; EIA and Alpaca usage comes from rate-limit headers on the existing probes. In bdobb a pure helper module (`src/lib/providerUsage.ts`) validates and formats it; `deriveProvider` exposes it as `Provider.usage`; two components render it.

**Tech Stack:** key-maint: Python 3.12, FastAPI, httpx, pytest (sync tests driving coroutines with `asyncio.run`). bdobb: React + TypeScript, vitest + Testing Library, pnpm.

**Spec:** `docs/superpowers/specs/2026-10-17-provider-api-usage-design.md` (this worktree).

**Repos and branches (both off `release/v3`, both local, nothing pushed):**
- key-maint: `~/Developer/openbq-docker-api-usage-v3` (Adventures-OpenBQ/openbq-docker), branch `claude/v3-provider-api-usage`. Work in `key-maint/`.
- bdobb: `~/Developer/openbq-bdobb-api-usage-v3` (Adventures-OpenBQ/bdobb), branch `claude/v3-provider-api-usage`.

Before every commit run `pwd` and confirm you are in the repo the task names.

## Global Constraints

- Usage is informational: it never changes a check's `result`, `detail` or `code`.
- `detail` stays built from status codes only; vendor numbers live only in `usage`.
- Only the **credential** check carries `usage`; absent = vendor does not report it or it did not parse.
- Wire shape: `usage?: { used: number, limit: number, window: "day" | "hour" | "minute" | "period", resets_at?: string (UTC ISO-8601), extra?: number }`.
- EODHD probe: `GET https://eodhd.com/api/user` with `api_token`, `fmt=json`. Intrinio probe: `GET https://api-v2.intrinio.com/account/current_usage` with the existing `api_key` query param.
- Header windows: `eia` → hour, `alpaca` → minute. No other provider's headers are parsed.
- Card line: `API calls: 1,234 / 100,000 today` (`today` / `this hour` / `this minute` / `this period`, numbers via `toLocaleString()`).
- Details block: `1,234 of 100,000 calls today (1.2%)`; `Resets 00:00 UTC · in 9h 12m` when `resets_at` is present; `Extra calls remaining: 5,000` when `extra` > 0; `As of <checked_at>` via `formatCheckedAt`.
- No polling, no thresholds/colours, no change to the legacy `KeysRenderer` table or the Library provider badge.
- key-maint tests: from `key-maint/`, `uv run --python 3.12 --extra dev pytest -q` (baseline on release/v3: 203 passed). Delete the `uv.lock` and `key_maint.egg-info/` it creates; never commit them.
- bdobb tests: `pnpm install --frozen-lockfile` once, then `pnpm vitest run <file>`; finish with `pnpm typecheck` and `pnpm lint`.

## Review Focus

1. EODHD answers 200 with a non-JSON body (an HTML error page): the check stays `ok`, no usage, nothing raises. → Task 1 (`test_non_json_body_is_none`) and Task 2 (`test_ok_with_unparseable_body_keeps_result_and_has_no_usage`).
2. EODHD's counter belongs to yesterday (no request since midnight GMT): used shows 0, not yesterday's count. → Task 1 (`test_eodhd_stale_date_is_zero_used`).
3. Numbers arrive as strings, booleans, negatives or "unlimited": strings parse, the rest drop usage instead of showing garbage. → Task 1 (`test_eodhd_bad_limit_is_none`) and Task 3 (`drops usage with non-numeric or negative values`).
4. After Details → Retest, the card and Details show the fresh usage, not the full run's stale one. → Task 5.
5. `resets_at` in the past or unparseable (clock skew, odd vendor value): no negative countdown, no "Invalid Date". → Task 3 (`usageResetLine` tests).

---

### Task 1: key-maint usage parser

**Repo:** `~/Developer/openbq-docker-api-usage-v3/key-maint`

**Files:**
- Create: `key-maint/app/usage.py`
- Test: `key-maint/tests/test_usage.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_usage(provider_id: str, resp: httpx.Response, now: datetime | None = None) -> dict | None` and `HEADER_WINDOWS: dict[str, str]`. Returned dict keys: `used` (int), `limit` (int), `window` (str), optional `resets_at` (str, `%Y-%m-%dT%H:%M:%SZ`), optional `extra` (int). Never raises.

- [ ] **Step 1: Write the failing tests**

`key-maint/tests/test_usage.py`:

```python
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

from datetime import UTC, datetime

import httpx

from app.usage import parse_usage

NOW = datetime(2026, 10, 17, 14, 48, tzinfo=UTC)


def _json(body, headers=None):
    return httpx.Response(200, json=body, headers=headers or {})


def _eodhd(**over):
    body = {"apiRequests": 1234, "apiRequestsDate": "2026-10-17",
            "dailyRateLimit": 100000, "extraLimit": 5000}
    body.update(over)
    return body


class TestEodhd:
    def test_eodhd_today(self):
        assert parse_usage("eodhd", _json(_eodhd()), NOW) == {
            "used": 1234, "limit": 100000, "window": "day",
            "resets_at": "2026-10-18T00:00:00Z", "extra": 5000,
        }

    def test_eodhd_numeric_strings(self):
        u = parse_usage("eodhd", _json(_eodhd(apiRequests="1234", dailyRateLimit="100000",
                                              extraLimit="5000")), NOW)
        assert (u["used"], u["limit"], u["extra"]) == (1234, 100000, 5000)

    def test_eodhd_stale_date_is_zero_used(self):
        u = parse_usage("eodhd", _json(_eodhd(apiRequestsDate="2026-10-16")), NOW)
        assert u["used"] == 0 and u["limit"] == 100000

    def test_eodhd_missing_date_is_none(self):
        body = _eodhd()
        del body["apiRequestsDate"]
        assert parse_usage("eodhd", _json(body), NOW) is None

    def test_eodhd_bad_limit_is_none(self):
        for bad in ("unlimited", 0, True, -5, None):
            assert parse_usage("eodhd", _json(_eodhd(dailyRateLimit=bad)), NOW) is None, bad

    def test_eodhd_bad_used_today_is_none(self):
        assert parse_usage("eodhd", _json(_eodhd(apiRequests="lots")), NOW) is None

    def test_eodhd_no_extra_key_when_missing(self):
        body = _eodhd()
        del body["extraLimit"]
        assert "extra" not in parse_usage("eodhd", _json(body), NOW)

    def test_non_json_body_is_none(self):
        assert parse_usage("eodhd", httpx.Response(200, text="<html>oops</html>"), NOW) is None
        assert parse_usage("eodhd", httpx.Response(200, content=b"\xff\xfe"), NOW) is None
        assert parse_usage("eodhd", _json([1, 2]), NOW) is None


class TestIntrinio:
    def test_picks_the_most_used_code(self):
        body = [
            {"access_code": "a", "count": 10, "limit": 1000, "seconds_until_reset": 60},
            {"access_code": "b", "count": "90", "limit": "100", "seconds_until_reset": "3600"},
        ]
        assert parse_usage("intrinio", _json(body), NOW) == {
            "used": 90, "limit": 100, "window": "period",
            "resets_at": "2026-10-17T15:48:00Z",
        }

    def test_skips_zero_limit_and_junk_entries(self):
        body = [{"count": 5, "limit": 0}, "junk",
                {"count": 1, "limit": 10}]
        u = parse_usage("intrinio", _json(body), NOW)
        assert (u["used"], u["limit"]) == (1, 10) and "resets_at" not in u

    def test_object_wrapping_a_list(self):
        body = {"usage": [{"count": 3, "limit": 30}]}
        assert parse_usage("intrinio", _json(body), NOW)["used"] == 3

    def test_empty_is_none(self):
        assert parse_usage("intrinio", _json([]), NOW) is None
        assert parse_usage("intrinio", _json({}), NOW) is None


class TestHeaders:
    def test_eia_hourly(self):
        r = _json({}, {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "988"})
        assert parse_usage("eia", r, NOW) == {"used": 12, "limit": 1000, "window": "hour"}

    def test_alpaca_minute_with_epoch_reset(self):
        reset = int(datetime(2026, 10, 17, 14, 49, tzinfo=UTC).timestamp())
        r = _json({}, {"X-RateLimit-Limit": "200", "X-RateLimit-Remaining": "150",
                       "X-RateLimit-Reset": str(reset)})
        assert parse_usage("alpaca", r, NOW) == {
            "used": 50, "limit": 200, "window": "minute", "resets_at": "2026-10-17T14:49:00Z",
        }

    def test_missing_garbage_or_inverted_headers_are_none(self):
        assert parse_usage("eia", _json({}), NOW) is None
        assert parse_usage("eia", _json({}, {"x-ratelimit-limit": "x",
                                             "x-ratelimit-remaining": "1"}), NOW) is None
        assert parse_usage("eia", _json({}, {"x-ratelimit-limit": "10",
                                             "x-ratelimit-remaining": "11"}), NOW) is None

    def test_unmapped_provider_is_never_parsed(self):
        r = _json({}, {"x-ratelimit-limit": "10", "x-ratelimit-remaining": "9"})
        assert parse_usage("fmp", r, NOW) is None


def test_defaults_now_to_the_current_time():
    today = datetime.now(UTC).date().isoformat()
    assert parse_usage("eodhd", _json(_eodhd(apiRequestsDate=today)))["used"] == 1234
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `key-maint/`): `uv run --python 3.12 --extra dev pytest tests/test_usage.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.usage'`.

- [ ] **Step 3: Write the implementation**

`key-maint/app/usage.py`:

```python
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

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
    except Exception:  # never let usage parsing break a credential check
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --python 3.12 --extra dev pytest tests/test_usage.py -q`
Expected: all pass. Then `uv run --python 3.12 --extra dev ruff check app/usage.py tests/test_usage.py` → no findings.

- [ ] **Step 5: Commit**

```bash
rm -rf uv.lock key_maint.egg-info
pwd   # must end in openbq-docker-api-usage-v3/key-maint
git add app/usage.py tests/test_usage.py
git commit -m "feat(key-maint): parse vendor API usage from probe responses"
```

---

### Task 2: key-maint carries usage on the credential check

**Repo:** `~/Developer/openbq-docker-api-usage-v3/key-maint`

**Files:**
- Modify: `key-maint/app/probes.py` (`Check` dataclass ~line 24; `_probe_credential` ok branch ~line 87)
- Modify: `key-maint/app/server.py:123-125` (`_check_dict`)
- Modify: `key-maint/app/registry.py:39-47` (`_eodhd`), `:97-103` (`_intrinio`)
- Test: `key-maint/tests/test_probes.py` (append), `key-maint/tests/test_server.py` (append), `key-maint/tests/test_registry.py` (append)

**Interfaces:**
- Consumes: `parse_usage(provider_id, resp)` from Task 1.
- Produces: `Check.usage: dict | None = None` (new last field, default None, so every existing positional `Check(...)` call still works); `_check_dict(c)` adds `"usage": c.usage` only when it is not None. All three routes that serialise checks (`/keys`, `/keys/{env_var}/test`, the provider test route; `server.py` lines ~192, ~216, ~229) already go through `_check_dict`, so none of them change.

- [ ] **Step 1: Write the failing tests**

Append to `key-maint/tests/test_probes.py`:

```python
class TestUsage:
    """Usage rides on an ok credential check and never changes its verdict."""

    def _eodhd_user(self, **over):
        from datetime import UTC, datetime
        body = {"apiRequests": 1234, "apiRequestsDate": datetime.now(UTC).date().isoformat(),
                "dailyRateLimit": 100000, "extraLimit": 0}
        body.update(over)
        return body

    def test_ok_eodhd_check_carries_usage(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=self._eodhd_user())

        c = run({"EODHD_API_KEY": REAL_KEY}, handler)["EODHD_API_KEY"]
        assert (c.result, c.detail, c.code) == ("ok", "HTTP 200", None)
        assert c.usage["used"] == 1234 and c.usage["window"] == "day"
        assert seen["path"] == "/api/user"
        assert seen["params"] == {"api_token": REAL_KEY, "fmt": "json"}

    def test_ok_with_unparseable_body_keeps_result_and_has_no_usage(self):
        c = _probe_with(status=200, body="<html>maintenance</html>")
        assert (c.result, c.detail) == ("ok", "HTTP 200")
        assert c.usage is None

    def test_failed_checks_never_carry_usage(self):
        for status in (401, 429, 500):
            c = _probe_with(status=status, body='{"apiRequests": 1}')
            assert c.usage is None, status

    def test_intrinio_probe_hits_current_usage(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[{"count": 5, "limit": 50}])

        c = run({"INTRINIO_API_KEY": REAL_KEY}, handler, env_var="INTRINIO_API_KEY")[
            "INTRINIO_API_KEY"]
        assert seen["path"] == "/account/current_usage"
        assert seen["params"] == {"api_key": REAL_KEY}
        assert c.usage == {"used": 5, "limit": 50, "window": "period"}

    def test_eia_usage_from_headers(self):
        def handler(request):
            return httpx.Response(200, json={"response": {}},
                                  headers={"x-ratelimit-limit": "1000",
                                           "x-ratelimit-remaining": "999"})

        c = run({"EIA_API_KEY": REAL_KEY}, handler, env_var="EIA_API_KEY")["EIA_API_KEY"]
        assert c.result == "ok"
        assert c.usage == {"used": 1, "limit": 1000, "window": "hour"}

    def test_check_without_usage_still_builds_positionally(self):
        assert Check("credential", "ok", "HTTP 200", None, "t").usage is None
```

Append to `key-maint/tests/test_server.py`:

```python
def test_check_dict_includes_usage_only_when_present():
    from app.probes import Check
    from app.server import _check_dict

    plain = _check_dict(Check("credential", "ok", "HTTP 200", None, "t"))
    assert "usage" not in plain
    u = {"used": 1, "limit": 10, "window": "day"}
    assert _check_dict(Check("credential", "ok", "HTTP 200", None, "t", usage=u))["usage"] == u
```

Append to `key-maint/tests/test_registry.py`:

```python
def test_eodhd_and_intrinio_probe_their_usage_endpoints():
    from app.registry import PROVIDERS

    e = PROVIDERS["EODHD_API_KEY"].probe.build({"EODHD_API_KEY": "YOUR_KEY"})
    assert str(e.url).startswith("https://eodhd.com/api/user?")
    i = PROVIDERS["INTRINIO_API_KEY"].probe.build({"INTRINIO_API_KEY": "YOUR_KEY"})
    assert str(i.url).startswith("https://api-v2.intrinio.com/account/current_usage?")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --python 3.12 --extra dev pytest tests/test_probes.py tests/test_server.py tests/test_registry.py -q`
Expected: the new tests FAIL (`TypeError: ... unexpected keyword argument 'usage'`, `AttributeError: 'Check' object has no attribute 'usage'`, path assertions on `/api/eod/AAPL.US` and `/companies/AAPL`).

- [ ] **Step 3: Implement**

In `key-maint/app/probes.py`, add the import next to the other `app.` imports:

```python
from app.usage import parse_usage
```

Add the field as the last line of `Check` (after `checked_at: str`):

```python
    # The vendor's API usage, set only on an ok credential check whose
    # provider reports it (app.usage). Informational: never ranks or fails.
    usage: dict | None = None
```

In `_probe_credential`, replace the ok return (`return Check("credential", "ok", f"HTTP {status}", None, _now())`) with:

```python
        return Check("credential", "ok", f"HTTP {status}", None, _now(),
                     usage=parse_usage(provider.provider_id, resp))
```

In `key-maint/app/server.py`, replace `_check_dict` with:

```python
def _check_dict(c: Check) -> dict:
    d = {"result": c.result, "detail": c.detail, "kind": c.kind,
         "code": c.code, "checked_at": c.checked_at}
    if c.usage is not None:
        d["usage"] = c.usage
    return d
```

In `key-maint/app/registry.py`, replace the body of `_eodhd`'s return:

```python
    # /api/user validates the key (401 on a bad one) without spending an API
    # call, and its body carries the day's usage (app.usage).
    return httpx.Request(
        "GET", "https://eodhd.com/api/user", params={"api_token": k, "fmt": "json"}
    )
```

and `_intrinio`'s return:

```python
    # current_usage validates the key (401 on a bad one) and reports usage.
    return httpx.Request(
        "GET", "https://api-v2.intrinio.com/account/current_usage", params={"api_key": k}
    )
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run --python 3.12 --extra dev pytest -q` then `uv run --python 3.12 --extra dev ruff check .`
Expected: 203 + Task 1 + Task 2 tests pass, ruff clean. If an existing test pinned the old EODHD/Intrinio URL, update only that URL expectation and say so in the commit body.

- [ ] **Step 5: Commit**

```bash
rm -rf uv.lock key_maint.egg-info
pwd   # must end in openbq-docker-api-usage-v3/key-maint
git add app/probes.py app/server.py app/registry.py tests/test_probes.py tests/test_server.py tests/test_registry.py
git commit -m "feat(key-maint): report API usage on the credential check

EODHD and Intrinio probe their free usage endpoints; EIA and Alpaca
usage comes from rate-limit headers on the existing probes."
```

---

### Task 3: bdobb usage type, guard and formatting

**Repo:** `~/Developer/openbq-bdobb-api-usage-v3` (run `pnpm install --frozen-lockfile` first if `node_modules/` is absent)

**Files:**
- Modify: `src/lib/providerKeys.ts:136-142` (`KeyCheck`)
- Create: `src/lib/providerUsage.ts`
- Modify: `src/lib/providerAvailability.ts` (`Provider` type ~line 19; `deriveProvider` `base` ~line 120)
- Test: `src/lib/providerUsage.test.ts` (create), `src/lib/providerAvailability.test.ts` (append)

**Interfaces:**
- Consumes: the wire shape from Task 2 inside `KeysRow.checks[]`.
- Produces (from `src/lib/providerKeys.ts`): `type UsageWindow = "day" | "hour" | "minute" | "period"`, `type Usage = { used: number; limit: number; window: UsageWindow; resets_at?: string; extra?: number }`, `KeyCheck.usage?: Usage`.
- Produces (from `src/lib/providerUsage.ts`): `credentialUsage(checks: KeyCheck[] | undefined): Usage | undefined`, `usageCardLine(u: Usage): string`, `usageSummary(u: Usage): string`, `usageResetLine(u: Usage, now?: Date): string | undefined`.
- Produces (from `src/lib/providerAvailability.ts`): `Provider.usage?: Usage`.

- [ ] **Step 1: Write the failing tests**

`src/lib/providerUsage.test.ts`:

```ts
// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { KeyCheck } from "./providerKeys";
import { credentialUsage, usageCardLine, usageResetLine, usageSummary } from "./providerUsage";

const cred = (usage: unknown): KeyCheck => ({ result: "ok", detail: "HTTP 200", kind: "credential", usage } as KeyCheck);
const n = (x: number) => x.toLocaleString();

describe("credentialUsage", () => {
  it("takes the credential check's usage", () => {
    const u = { used: 1234, limit: 100000, window: "day", resets_at: "2026-10-18T00:00:00Z", extra: 5000 };
    expect(credentialUsage([{ result: "ok", detail: "", kind: "connectivity" }, cred(u)])).toEqual(u);
  });

  it("ignores usage on a connectivity check", () => {
    const c = { result: "ok", detail: "", kind: "connectivity", usage: { used: 1, limit: 2, window: "day" } } as KeyCheck;
    expect(credentialUsage([c])).toBeUndefined();
  });

  it("is undefined without checks or usage", () => {
    expect(credentialUsage(undefined)).toBeUndefined();
    expect(credentialUsage([cred(undefined)])).toBeUndefined();
  });

  it("drops usage with non-numeric or negative values", () => {
    for (const bad of [
      { used: "12", limit: 100, window: "day" },
      { used: 1, limit: 0, window: "day" },
      { used: -1, limit: 100, window: "day" },
      { used: 1, limit: Number.NaN, window: "day" },
      { used: 1, limit: 100, window: "week" },
      "1/100",
      null,
    ]) {
      expect(credentialUsage([cred(bad)])).toBeUndefined();
    }
  });

  it("drops a bad optional field but keeps the usage", () => {
    expect(credentialUsage([cred({ used: 1, limit: 2, window: "hour", resets_at: 5, extra: "x" })])).toEqual({
      used: 1, limit: 2, window: "hour",
    });
  });
});

describe("formatting", () => {
  const day = { used: 1234, limit: 100000, window: "day" } as const;

  it("card line per window", () => {
    expect(usageCardLine(day)).toBe(`API calls: ${n(1234)} / ${n(100000)} today`);
    expect(usageCardLine({ used: 12, limit: 5000, window: "hour" })).toBe(`API calls: 12 / ${n(5000)} this hour`);
    expect(usageCardLine({ used: 1, limit: 200, window: "minute" })).toBe("API calls: 1 / 200 this minute");
    expect(usageCardLine({ used: 1, limit: 2, window: "period" })).toBe("API calls: 1 / 2 this period");
  });

  it("summary with one-decimal percentage", () => {
    expect(usageSummary(day)).toBe(`${n(1234)} of ${n(100000)} calls today (1.2%)`);
  });

  it("reset line within a day, beyond a day, past, and unparseable", () => {
    const now = new Date("2026-10-17T14:48:00Z");
    expect(usageResetLine({ ...day, resets_at: "2026-10-18T00:00:00Z" }, now)).toBe("Resets 00:00 UTC · in 9h 12m");
    expect(usageResetLine({ ...day, resets_at: "2026-10-20T06:00:00Z" }, now)).toBe("Resets 2026-10-20 06:00 UTC · in 2d 15h");
    expect(usageResetLine({ ...day, resets_at: "2026-10-17T14:48:30Z" }, now)).toBe("Resets 14:48 UTC · in under a minute");
    expect(usageResetLine({ ...day, resets_at: "2026-10-17T14:00:00Z" }, now)).toBe("Resets 14:00 UTC");
    expect(usageResetLine({ ...day, resets_at: "soon" }, now)).toBeUndefined();
    expect(usageResetLine(day, now)).toBeUndefined();
  });
});
```

Append to `src/lib/providerAvailability.test.ts`:

```ts
describe("deriveProvider — usage", () => {
  it("exposes the credential check's usage", () => {
    const usage = { used: 5, limit: 50, window: "period" as const };
    const p = deriveProvider(row({
      provider: "Intrinio", env_var: "INTRINIO_API_KEY", status: "set",
      test: { result: "ok", detail: "HTTP 200" },
      checks: [{ result: "ok", detail: "HTTP 200", kind: "credential", usage }],
    }));
    expect(p.usage).toEqual(usage);
  });

  it("has no usage when no check carries it", () => {
    const p = deriveProvider(row({ provider: "FMP", env_var: "FMP_API_KEY", status: "set", test: { result: "ok", detail: "HTTP 200" } }));
    expect(p.usage).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm vitest run src/lib/providerUsage.test.ts src/lib/providerAvailability.test.ts`
Expected: FAIL — cannot resolve `./providerUsage`; `p.usage` undefined in the first usage test.

- [ ] **Step 3: Implement**

In `src/lib/providerKeys.ts`, add above `export type KeyCheck` and extend it:

```ts
export type UsageWindow = "day" | "hour" | "minute" | "period";

/** A vendor's API usage, as key-maint reports it on the credential check. */
export type Usage = { used: number; limit: number; window: UsageWindow; resets_at?: string; extra?: number };

export type KeyCheck = {
  result: string;
  detail: string;
  kind?: "credential" | "connectivity";
  code?: DiagnosticCode;
  checked_at?: string;
  /** Untrusted until credentialUsage (lib/providerUsage) has checked it. */
  usage?: Usage;
};
```

`src/lib/providerUsage.ts`:

```ts
// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import type { KeyCheck, Usage, UsageWindow } from "./providerKeys";

const WINDOWS: readonly UsageWindow[] = ["day", "hour", "minute", "period"];

const WINDOW_PHRASE: Record<UsageWindow, string> = {
  day: "today",
  hour: "this hour",
  minute: "this minute",
  period: "this period",
};

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;

/**
 * The credential check's usage, or undefined when key-maint sent none or sent
 * one this app cannot trust. key-maint's JSON is untrusted like any other: a
 * bad `used`/`limit`/`window` drops the whole usage, a bad optional field only
 * drops that field.
 */
export function credentialUsage(checks: KeyCheck[] | undefined): Usage | undefined {
  const raw: unknown = checks?.find((c) => c?.kind === "credential")?.usage;
  if (typeof raw !== "object" || raw === null) return undefined;
  const { used, limit, window, resets_at, extra } = raw as Record<string, unknown>;
  if (!isCount(used) || !isCount(limit) || limit === 0) return undefined;
  if (!WINDOWS.includes(window as UsageWindow)) return undefined;
  return {
    used,
    limit,
    window: window as UsageWindow,
    ...(typeof resets_at === "string" ? { resets_at } : {}),
    ...(isCount(extra) ? { extra } : {}),
  };
}

/** The dashboard card's line: "API calls: 1,234 / 100,000 today". */
export function usageCardLine(u: Usage): string {
  return `API calls: ${u.used.toLocaleString()} / ${u.limit.toLocaleString()} ${WINDOW_PHRASE[u.window]}`;
}

/** Details' headline: "1,234 of 100,000 calls today (1.2%)". */
export function usageSummary(u: Usage): string {
  const pct = ((u.used / u.limit) * 100).toFixed(1);
  return `${u.used.toLocaleString()} of ${u.limit.toLocaleString()} calls ${WINDOW_PHRASE[u.window]} (${pct}%)`;
}

/**
 * "Resets 00:00 UTC · in 9h 12m"; the date is added when the reset is a day or
 * more away, and the countdown is dropped once the time has passed. Undefined
 * without a parseable resets_at -- never "Invalid Date".
 */
export function usageResetLine(u: Usage, now: Date = new Date()): string | undefined {
  if (u.resets_at === undefined) return undefined;
  const at = new Date(u.resets_at);
  if (Number.isNaN(at.getTime())) return undefined;
  const iso = at.toISOString();
  const ms = at.getTime() - now.getTime();
  const when = ms < 86_400_000 ? `${iso.slice(11, 16)} UTC` : `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
  return ms > 0 ? `Resets ${when} · in ${until(ms)}` : `Resets ${when}`;
}

/** The two largest units of a positive duration: "2d 15h", "9h 12m", "4m". */
function until(ms: number): string {
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "under a minute";
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
```

In `src/lib/providerAvailability.ts`:
- add `type Usage,` to the existing `import { … } from "./providerKeys";` list and add `import { credentialUsage } from "./providerUsage";` below it;
- add `usage?: Usage;` as the last field of `export type Provider`;
- add `usage: credentialUsage(row.checks),` as the last entry of `base` in `deriveProvider` (after `checks: row.checks,`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm vitest run src/lib/providerUsage.test.ts src/lib/providerAvailability.test.ts` then `pnpm typecheck`
Expected: all pass, no type errors.

- [ ] **Step 5: Commit**

```bash
pwd   # must be ~/Developer/openbq-bdobb-api-usage-v3
git add src/lib/providerKeys.ts src/lib/providerUsage.ts src/lib/providerUsage.test.ts src/lib/providerAvailability.ts src/lib/providerAvailability.test.ts
git commit -m "feat(keys): validate and format provider API usage"
```

---

### Task 4: bdobb dashboard card and Details block

**Repo:** `~/Developer/openbq-bdobb-api-usage-v3`

**Files:**
- Modify: `src/components/keys/ProviderDashboard.tsx:119` (after the Credential line)
- Modify: `src/components/keys/ProviderDetailsDialog.tsx` (imports ~line 3; after the `{checks.length > 0 ? … : null}` expression that ends just before `{manageOpen && tier === 3 ? (`)
- Test: `src/components/keys/ProviderDashboard.test.tsx`, `src/components/keys/ProviderDetailsDialog.test.tsx` (append)

**Interfaces:**
- Consumes: `Provider.usage`, `usageCardLine`, `usageSummary`, `usageResetLine` from Task 3; the file-local `formatCheckedAt(iso)` in `ProviderDetailsDialog.tsx`.
- Produces: rendered text only.

- [ ] **Step 1: Write the failing tests**

Append inside `describe("ProviderDashboard", …)` in `src/components/keys/ProviderDashboard.test.tsx`:

```tsx
  it("shows an API usage line only on cards whose credential check reports usage", () => {
    const withUsage: KeysRow[] = [
      { provider: "EODHD", env_var: "EODHD_API_KEY", status: "set", test: { result: "ok", detail: "HTTP 200" },
        checks: [{ result: "ok", detail: "HTTP 200", kind: "credential", usage: { used: 1234, limit: 100000, window: "day" } }] },
      { provider: "FRED", env_var: "FRED_API_KEY", status: "set", test: { result: "ok", detail: "HTTP 200" } },
    ];
    setup({ rows: withUsage });
    expect(screen.getByText(`API calls: ${(1234).toLocaleString()} / ${(100000).toLocaleString()} today`)).toBeInTheDocument();
    expect(screen.getAllByText(/^API calls:/)).toHaveLength(1);
  });
```

Append inside `describe("ProviderDetailsDialog", …)` in `src/components/keys/ProviderDetailsDialog.test.tsx`:

```tsx
  it("shows the API usage block with reset, extra balance and as-of time", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-17T14:48:00Z"));
    try {
      const checkedAt = "2026-10-17T14:48:00Z";
      const p = derive({
        provider: "EODHD", env_var: "EODHD_API_KEY", status: "set",
        test: { result: "ok", detail: "HTTP 200", checked_at: checkedAt },
        checks: [{ result: "ok", detail: "HTTP 200", kind: "credential", checked_at: checkedAt,
          usage: { used: 1234, limit: 100000, window: "day", resets_at: "2026-10-18T00:00:00Z", extra: 5000 } }],
      });
      render(<ProviderDetailsDialog provider={p} tier={2} backendName="key-maint" onClose={vi.fn()} onTest={vi.fn()} onSubmit={vi.fn()} />);
      expect(screen.getByText("API usage")).toBeInTheDocument();
      expect(screen.getByText(`${(1234).toLocaleString()} of ${(100000).toLocaleString()} calls today (1.2%)`)).toBeInTheDocument();
      expect(screen.getByText("Resets 00:00 UTC · in 9h 12m")).toBeInTheDocument();
      expect(screen.getByText(`Extra calls remaining: ${(5000).toLocaleString()}`)).toBeInTheDocument();
      expect(screen.getByText(`As of ${new Date(checkedAt).toLocaleString()}`)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("omits the optional usage lines and the whole block when absent", () => {
    const p = derive({
      provider: "EIA", env_var: "EIA_API_KEY", status: "set", test: { result: "ok", detail: "HTTP 200" },
      checks: [{ result: "ok", detail: "HTTP 200", kind: "credential", usage: { used: 1, limit: 1000, window: "hour", extra: 0 } }],
    });
    const { unmount } = render(<ProviderDetailsDialog provider={p} tier={2} backendName="km" onClose={vi.fn()} onTest={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByText(`1 of ${(1000).toLocaleString()} calls this hour (0.1%)`)).toBeInTheDocument();
    expect(screen.queryByText(/^Resets/)).toBeNull();
    expect(screen.queryByText(/^Extra calls/)).toBeNull();
    expect(screen.getByText("As of time not recorded")).toBeInTheDocument();
    unmount();

    const none = derive({ provider: "FRED", env_var: "FRED_API_KEY", status: "set", test: { result: "ok", detail: "HTTP 200" } });
    render(<ProviderDetailsDialog provider={none} tier={2} backendName="km" onClose={vi.fn()} onTest={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.queryByText("API usage")).toBeNull();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm vitest run src/components/keys/ProviderDashboard.test.tsx src/components/keys/ProviderDetailsDialog.test.tsx`
Expected: the three new tests FAIL (text not found); existing tests pass.

- [ ] **Step 3: Implement**

`src/components/keys/ProviderDashboard.tsx` — add the import:

```tsx
import { usageCardLine } from "../../lib/providerUsage";
```

and directly after `<p className="bd-muted">{`Credential: ${CREDENTIAL_LABEL[p.credential]}`}</p>`:

```tsx
              {p.usage !== undefined ? <p className="bd-muted">{usageCardLine(p.usage)}</p> : null}
```

`src/components/keys/ProviderDetailsDialog.tsx` — add the import:

```tsx
import { usageResetLine, usageSummary } from "../../lib/providerUsage";
```

and insert this between the closing `) : null}` of the `{checks.length > 0 ? (` expression and `{manageOpen && tier === 3 ? (`:

```tsx
      {provider.usage !== undefined ? (
        // From the credential check; as old as that check (spec: refreshed only
        // when a test runs).
        <div className="bd-provider-diagnostic">
          <h3>API usage</h3>
          <p>{usageSummary(provider.usage)}</p>
          {usageResetLine(provider.usage) !== undefined ? (
            <p className="bd-muted">{usageResetLine(provider.usage)}</p>
          ) : null}
          {provider.usage.extra !== undefined && provider.usage.extra > 0 ? (
            <p className="bd-muted">{`Extra calls remaining: ${provider.usage.extra.toLocaleString()}`}</p>
          ) : null}
          <p className="bd-muted">{`As of ${formatCheckedAt(provider.checks?.find((c) => c.kind === "credential")?.checked_at)}`}</p>
        </div>
      ) : null}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm vitest run src/components/keys/` then `pnpm typecheck && pnpm lint`
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
pwd   # must be ~/Developer/openbq-bdobb-api-usage-v3
git add src/components/keys/ProviderDashboard.tsx src/components/keys/ProviderDashboard.test.tsx src/components/keys/ProviderDetailsDialog.tsx src/components/keys/ProviderDetailsDialog.test.tsx
git commit -m "feat(keys): show provider API usage on the card and in Details"
```

---

### Task 5: bdobb per-row Test merges key-maint's `{checks, test}` reply

**Why:** key-maint's `GET /keys/{env_var}/test` answers `{"checks": [...], "test": {...}}` (`key-maint/app/server.py:216-217`), but `KeysPanel.testKey` reads `result`/`detail` off the top level, so on release/v3 a Details → Test/Retest blanks the result and leaves `checks` (and now usage) from the previous full run. The spec's "usage refreshes whenever a test runs" needs the Retest path to carry `checks`. The flat shape keeps working for the existing tests.

**Repo:** `~/Developer/openbq-bdobb-api-usage-v3`

**Files:**
- Modify: `src/components/dialogs/KeysPanel.tsx:103-133` (`testKey`)
- Test: `src/components/dialogs/KeysPanel.test.tsx` (append next to "merges a single-row test result in place without a full re-probe", ~line 327)

**Interfaces:**
- Consumes: `testProviderKey(backend, widget, envVar): Promise<unknown>` (`src/lib/dataClient.ts:347`); `KeyCheck` (`src/lib/providerKeys.ts`); `Provider.usage` (Task 3).
- Produces: after a per-row Test the row has `test` = the reply's `test` and `checks` = the reply's `checks` when the reply has that shape.

- [ ] **Step 1: Write the failing test**

Append after the "merges a single-row test result in place without a full re-probe" test in `src/components/dialogs/KeysPanel.test.tsx`:

```tsx
  it("merges key-maint's {checks, test} reply so a Retest refreshes checks and usage", async () => {
    connectKeyMaint();
    fetchWidgetData.mockResolvedValue(keysPayload);
    const usage = { used: 42, limit: 100000, window: "day" };
    const credential = { result: "ok", detail: "HTTP 200", kind: "credential", checked_at: "2026-10-17T14:48:00Z", usage };
    testProviderKey.mockResolvedValue({ checks: [credential], test: credential });
    render(<KeysPanel backendId="km" />);
    await screen.findByRole("heading", { name: "FMP" });

    await userEvent.click(screen.getByRole("button", { name: "Details for FMP" }));
    await userEvent.click(screen.getByRole("button", { name: "Test" }));

    expect(await screen.findByText(`42 of ${(100000).toLocaleString()} calls today (0.0%)`)).toBeInTheDocument();
    expect(screen.getByText(/Credential check · /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retest" })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm vitest run src/components/dialogs/KeysPanel.test.tsx`
Expected: the new test FAILS (usage text not found); all existing tests pass.

- [ ] **Step 3: Implement**

In `src/components/dialogs/KeysPanel.tsx`, add `type KeyCheck` to an existing import from `../../lib/providerKeys` (or add `import type { KeyCheck } from "../../lib/providerKeys";`), then replace the body of `testKey`'s `try` block with:

```tsx
      const reply = (await testProviderKey(backend, widget, envVar)) as {
        result?: string;
        detail?: string;
        kind?: "credential" | "connectivity";
        code?: string;
        checked_at?: string;
        test?: unknown;
        checks?: unknown;
      };
      // key-maint answers {checks, test}; an older backend answered one flat
      // check. Either way only this row changes.
      const flat = typeof reply.test === "object" && reply.test !== null ? (reply.test as typeof reply) : reply;
      const checks = Array.isArray(reply.checks)
        ? (reply.checks.filter((c) => typeof c === "object" && c !== null) as KeyCheck[])
        : undefined;
      setData((prev: unknown) => {
        if (!isKeysPayload(prev)) return prev;
        return {
          ...prev,
          rows: prev.rows.map((row) =>
            row.env_var === envVar
              ? {
                  ...row,
                  test: {
                    result: flat.result ?? "",
                    detail: flat.detail ?? "",
                    kind: flat.kind,
                    // An unrecognised code is dropped by deriveProvider's guard, so
                    // this cast never widens a bad value onto the screen.
                    code: flat.code as DiagnosticCode | undefined,
                    checked_at: flat.checked_at,
                  },
                  // A flat reply carries no checks: keep the row's, as before.
                  ...(checks !== undefined ? { checks } : {}),
                }
              : row,
          ),
        };
      });
```

Keep the existing comment block above `testKey` and the `catch` unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm vitest run src/components/dialogs/KeysPanel.test.tsx src/components/keys/ src/lib/` then `pnpm typecheck && pnpm lint`
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
pwd   # must be ~/Developer/openbq-bdobb-api-usage-v3
git add src/components/dialogs/KeysPanel.tsx src/components/dialogs/KeysPanel.test.tsx
git commit -m "fix(keys): a per-row Test merges key-maint's {checks, test} reply"
```

---

## Final verification

- [ ] key-maint: `uv run --python 3.12 --extra dev pytest -q` and `ruff check .` clean; `rm -rf uv.lock key_maint.egg-info`; `git status` clean apart from the commits.
- [ ] bdobb: `pnpm vitest run`, `pnpm typecheck`, `pnpm lint` all clean.
- [ ] Live (needs a stack with real keys; report what could not be run): run key-maint from this branch with the user's `credentials.env`, then `curl -s -u <user>:<pass> '<key-maint>/keys?run_tests=true' | python3 -m json.tool | grep -A6 '"usage"'` and compare EODHD's figures with `https://eodhd.com/api/user` and Intrinio's with its dashboard. Alpaca's data-API headers are unverified: if Alpaca shows no `usage`, record that, do not add code.
- [ ] Nothing pushed; both branches stay local for the series' placement.
