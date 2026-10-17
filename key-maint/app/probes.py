# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Concurrent provider probes. Detail strings are built ONLY from status codes
and exception class names — never from URLs, bodies, or key material."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.catalog import _DETAIL as _CRED_DETAIL
from app.catalog import EXAMPLES, classify
from app.registry import LOCAL_PROVIDERS, PROVIDERS, provider_index
from app.usage import parse_usage

TIMEOUT_S = 5.0
CONNECTIVITY_TIMEOUT_S = 10.0
MAX_INFLIGHT = 4

WORST_RANK = {"no_response": 4, "error": 3, "auth_failed": 2, "skipped": 1, "ok": 0}


@dataclass(frozen=True)
class Check:
    kind: str
    # ok | auth_failed | error | no_response | skipped
    #
    # `no_response` and `error` are deliberately distinct: the widget paints
    # a vendor that never answered red, and one that answered with an error
    # amber. Collapsing them (as this did) made an outage indistinguishable
    # from a rejected request.
    result: str
    detail: str
    code: str | None
    checked_at: str
    # The vendor's API usage, set only on an ok credential check whose
    # provider reports it (app.usage). Informational: never ranks or fails.
    usage: dict | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def code_from_httpx_error(exc: httpx.HTTPError) -> str:
    """Map an httpx transport failure to a code by class then message. Message
    matching is a fallback: httpx folds DNS/refused/TLS into ConnectError, so
    the class alone cannot tell them apart."""
    msg = str(exc)
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout)):
        return "connect_timeout"
    if "Name or service not known" in msg or "NameResolutionError" in msg or "nodename" in msg:
        return "dns_failure"
    if "Connection refused" in msg:
        return "connect_refused"
    if "SSL" in msg or "certificate" in msg.lower():
        return "tls_error"
    if isinstance(exc, httpx.ConnectError):
        return "connect_refused"
    return "connect_timeout"


async def _probe_credential(client, env_var, values) -> Check:
    provider = PROVIDERS[env_var]
    if provider.probe is None:
        return Check("credential", "skipped", "no probe defined", None, _now())
    request = provider.probe.build(values)
    if request is None:
        return Check("credential", "skipped", "key not set", None, _now())
    try:
        resp = await client.send(request)
    except httpx.HTTPError as e:
        code = code_from_httpx_error(e)
        return Check("credential", "no_response", "the provider did not answer", code, _now())
    status = resp.status_code
    if status in (401, 403):
        return Check("credential", "auth_failed",
                     f"{_CRED_DETAIL['http_auth']} (HTTP {status})", "http_auth", _now())
    if resp.is_success:
        body = resp.text[:2000]
        for marker in provider.probe.invalid_markers:
            if marker in body:
                return Check("credential", "auth_failed",
                             f"{_CRED_DETAIL['http_auth']} (HTTP {status})", "http_auth", _now())
        return Check("credential", "ok", f"HTTP {status}", None, _now(),
                     usage=parse_usage(provider.provider_id, resp))
    if status == 429:
        return Check("credential", "error",
                     f"{_CRED_DETAIL['rate_limited']} (HTTP {status})", "rate_limited", _now())
    return Check("credential", "error",
                 f"{_CRED_DETAIL['upstream_error']} (HTTP {status})", "upstream_error", _now())


def worst(checks: list[Check]) -> Check:
    """The worst check by result rank: no_response > error > auth_failed >
    skipped > ok."""
    return max(checks, key=lambda c: WORST_RANK.get(c.result, 0))


async def _probe_connectivity(api_client, example, base_url, auth, sem=None) -> Check:
    """Fire the provider's one stored example request through the OpenBB API
    itself (not the vendor directly) and classify the response. A transport
    failure never reaches the API, so its detail is the fixed sentence below
    -- never the exception message, which can carry a URL."""
    async with sem or contextlib.nullcontext():
        try:
            resp = await api_client.get(
                f"{base_url.rstrip('/')}{example.path}",
                params=example.params, auth=auth,
                timeout=CONNECTIVITY_TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            return Check("connectivity", "no_response", "the backend did not answer",
                         code_from_httpx_error(e), _now())
    try:
        body = resp.json()
    except ValueError:
        body = {}
    result, code, detail = classify(resp.status_code, body)
    return Check("connectivity", result, detail, code, _now())


async def run_probes(
    values: dict[str, str],
    descriptor: list[dict] | None,
    base_url: str,
    auth,
    *,
    cred_client: httpx.AsyncClient | None = None,
    api_client: httpx.AsyncClient | None = None,
) -> dict[str, list[Check]]:
    """Probe every descriptor-named, installed, non-local provider that also
    has a stored example (app.catalog.EXAMPLES), keyed by provider_id. Rule
    (spec §4): keyed+value -> credential then connectivity; keyed, no value,
    auth optional -> connectivity only; keyed, no value, auth required/unknown
    -> both skipped ("key not set"); keyless -> connectivity only. Not-
    installed providers are never reached here -- rows.py fixes their skipped
    test on its own."""
    own_cred = cred_client is None
    own_api = api_client is None
    cred_client = cred_client or httpx.AsyncClient(timeout=TIMEOUT_S)
    api_client = api_client or httpx.AsyncClient(timeout=CONNECTIVITY_TIMEOUT_S)
    sem = asyncio.Semaphore(MAX_INFLIGHT)
    idx = provider_index()
    installed = {d.get("id") for d in (descriptor or [])
                 if d.get("id") and not d.get("local") and d.get("id") not in LOCAL_PROVIDERS}
    auth_of = {d.get("id"): d.get("auth", "unknown") for d in (descriptor or [])}
    try:
        async def one(pid):
            p = idx.get(pid)
            has_value = bool(p and values.get(p.env_var))
            if p is not None and not has_value and auth_of.get(pid, "unknown") != "optional":
                # keyed, no value, auth required (or unknown)
                return pid, [Check("credential", "skipped", "key not set", None, _now()),
                             Check("connectivity", "skipped", "key not set", None, _now())]
            checks: list[Check] = []
            if has_value:
                checks.append(await _probe_credential(cred_client, p.env_var, values))
            checks.append(await _probe_connectivity(api_client, EXAMPLES[pid], base_url, auth, sem))
            return pid, checks

        pids = [pid for pid in installed if pid in EXAMPLES]
        results = await asyncio.gather(*(one(pid) for pid in pids))
        return dict(results)
    finally:
        if own_cred:
            await cred_client.aclose()
        if own_api:
            await api_client.aclose()


_inflight: asyncio.Future | None = None


async def run_probes_joined(runner):
    """Join a run already in progress instead of firing a duplicate wave of
    vendor/API calls. `runner` is a zero-arg coroutine function returning the
    run's result. Two concurrent callers while a run is in flight both await
    the same Future and get the same result object."""
    global _inflight
    fut = _inflight
    if fut is not None and not fut.done():
        return await fut
    loop = asyncio.get_event_loop()
    fut = _inflight = loop.create_future()
    try:
        result = await runner()
        fut.set_result(result)
        return result
    except Exception as e:  # propagate to joiners, then clear
        fut.set_exception(e)
        raise
    finally:
        _inflight = None


async def probe_one_provider(
    env_var: str, values: dict[str, str], descriptor: list[dict] | None, base_url: str, auth
) -> list[Check]:
    """Probe a single provider by env_var. Backs the widget's per-row 'Test
    this service' action, which must not fire ~18 vendor requests to check
    one. Runs connectivity too, alongside the credential check, when the
    provider is installed, has a stored example, and has a value."""
    p = PROVIDERS[env_var]
    auth_of = {d.get("id"): d.get("auth", "unknown") for d in (descriptor or [])}
    installed = p.provider_id in auth_of
    async with (httpx.AsyncClient(timeout=TIMEOUT_S) as cc,
                httpx.AsyncClient(timeout=CONNECTIVITY_TIMEOUT_S) as ac):
        checks = [await _probe_credential(cc, env_var, values)]
        if installed and p.provider_id in EXAMPLES and values.get(env_var):
            checks.append(await _probe_connectivity(ac, EXAMPLES[p.provider_id], base_url, auth))
        return checks


async def probe_provider_by_id(provider_id: str, base_url: str, auth) -> list[Check]:
    """Probe a single keyless provider by provider_id (no credential leg)."""
    async with httpx.AsyncClient(timeout=CONNECTIVITY_TIMEOUT_S) as ac:
        return [await _probe_connectivity(ac, EXAMPLES[provider_id], base_url, auth)]
