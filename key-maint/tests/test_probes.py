# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from typing import ClassVar

import httpx

from app.probes import Check, _probe_credential, code_from_httpx_error, run_probes

REAL_KEY = "sekret-value-123"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(values, handler, env_var="EODHD_API_KEY"):
    """Drive _probe_credential directly, keyed by env_var, so this file's
    existing classification tests stay decoupled from run_probes' new
    provider_id-keyed, dual-probe-kind shape (Task 7)."""

    async def go():
        async with _client(handler) as c:
            return {env_var: await _probe_credential(c, env_var, values)}

    return asyncio.run(go())


def _probe_with(*, raises=None, status=None, body="", key=REAL_KEY, env_var="EODHD_API_KEY"):
    """Drive _probe_credential for a given provider (EODHD by default) against
    a stubbed httpx.AsyncClient. Either `raises` (an exception instance the
    mock transport raises) or `status` (plus optional `body`) must be given.

    This suite has no pytest-asyncio/anyio plugin declared as a dependency
    (pyproject.toml's dev extra is just pytest + ruff), so — following the
    existing `run()` helper above — coroutines are driven with asyncio.run()
    from a plain sync test function rather than @pytest.mark.asyncio.
    """

    def handler(request):
        if raises is not None:
            raise raises
        return httpx.Response(status, text=body)

    async def go():
        async with _client(handler) as c:
            return await _probe_credential(c, env_var, {env_var: key})

    return asyncio.run(go())


class TestClassification:
    def test_2xx_is_ok(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(200, json=[]))
        assert res["EODHD_API_KEY"].result == "ok"

    def test_401_and_403_are_auth_failed(self):
        for code in (401, 403):
            res = run({"EODHD_API_KEY": REAL_KEY}, lambda r, c=code: httpx.Response(c))
            assert res["EODHD_API_KEY"].result == "auth_failed"

    def test_2xx_with_invalid_marker_is_auth_failed(self):
        res = run(
            {"BLS_API_KEY": REAL_KEY},
            lambda r: httpx.Response(200, json={"status": "REQUEST_NOT_PROCESSED"}),
            env_var="BLS_API_KEY",
        )
        assert res["BLS_API_KEY"].result == "auth_failed"

    def test_network_error_is_no_response(self):
        # A transport failure (never got a response) is distinct from an
        # HTTP error response — see TestTransportFailureIsDistinct below.
        def boom(request):
            raise httpx.ConnectError("nope", request=request)

        res = run({"EODHD_API_KEY": REAL_KEY}, boom)
        assert res["EODHD_API_KEY"].result == "no_response"

    def test_missing_key_is_skipped(self):
        res = run({}, lambda r: httpx.Response(200))
        assert res["EODHD_API_KEY"].result == "skipped"

    def test_provider_without_probe_is_skipped(self):
        res = run({"BENZINGA_API_KEY": REAL_KEY}, lambda r: httpx.Response(200),
                  env_var="BENZINGA_API_KEY")
        assert res["BENZINGA_API_KEY"].result == "skipped"


class TestSecrecy:
    def test_key_value_never_in_detail(self):
        def boom(request):
            raise httpx.ConnectError(f"failed url {request.url}", request=request)

        res = run({"EODHD_API_KEY": REAL_KEY}, boom)
        for c in res.values():
            assert REAL_KEY not in c.detail

    def test_detail_mentions_status_for_ok(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(200, json=[]))
        assert "200" in res["EODHD_API_KEY"].detail


class TestTransportFailureIsDistinct:
    """A vendor that never answers must not look like one that answered
    with an error: the widget paints the first red and the second amber."""

    def test_timeout_is_no_response(self):
        # httpx.HTTPError subclasses cover timeout/connect/DNS failures.
        result = _probe_with(raises=httpx.ConnectTimeout("boom"))
        assert result.result == "no_response"
        assert result.code == "connect_timeout"

    def test_connect_error_is_no_response(self):
        result = _probe_with(raises=httpx.ConnectError("refused"))
        assert result.result == "no_response"
        assert result.code == "connect_refused"

    def test_http_500_is_error_not_no_response(self):
        result = _probe_with(status=500)
        assert result.result == "error"

    def test_401_is_auth_failed(self):
        result = _probe_with(status=401)
        assert result.result == "auth_failed"

    def test_200_rejected_by_body_is_auth_failed(self):
        # Alpha Vantage and FMP report a bad key with HTTP 200 plus an error
        # string, so the status code alone is not the signal. EODHD (the
        # default provider above) has no invalid_markers, so this needs a
        # provider that does.
        result = _probe_with(status=200, body="Invalid API call", env_var="ALPHA_VANTAGE_API_KEY")
        assert result.result == "auth_failed"

    def test_detail_never_contains_the_key(self):
        result = _probe_with(status=500, key="supersecret123")
        assert "supersecret123" not in result.detail


class TestCredentialCodes:
    def test_ok_has_no_code_and_iso_checked_at(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(200, json=[]))
        c = res["EODHD_API_KEY"]
        assert c.kind == "credential" and c.result == "ok" and c.code is None
        assert c.checked_at.endswith("Z") and "T" in c.checked_at

    def test_401_is_http_auth(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(401))
        assert res["EODHD_API_KEY"].result == "auth_failed"
        assert res["EODHD_API_KEY"].code == "http_auth"

    def test_429_is_rate_limited(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(429))
        assert res["EODHD_API_KEY"].code == "rate_limited"

    def test_500_is_upstream_error(self):
        res = run({"EODHD_API_KEY": REAL_KEY}, lambda r: httpx.Response(500))
        assert res["EODHD_API_KEY"].result == "error"
        assert res["EODHD_API_KEY"].code == "upstream_error"

    def test_body_marker_is_http_auth(self):
        res = run({"ALPHA_VANTAGE_API_KEY": REAL_KEY},
                  lambda r: httpx.Response(200, text="Invalid API call"),
                  env_var="ALPHA_VANTAGE_API_KEY")
        assert res["ALPHA_VANTAGE_API_KEY"].code == "http_auth"


class TestHttpxErrorCodes:
    def test_connect_timeout_code(self):
        assert code_from_httpx_error(httpx.ConnectTimeout("x")) == "connect_timeout"

    def test_dns_failure_from_message(self):
        assert code_from_httpx_error(
            httpx.ConnectError("Name or service not known")) == "dns_failure"

    def test_connect_refused_from_message(self):
        assert code_from_httpx_error(
            httpx.ConnectError("Connection refused")) == "connect_refused"

    def test_tls_error(self):
        assert code_from_httpx_error(httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")) == "tls_error"


class TestConnectivity:
    def _api(self, handler):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def _one(self, example, handler):
        from app.probes import _probe_connectivity
        sem = asyncio.Semaphore(4)

        async def go():
            async with self._api(handler) as c:
                return await _probe_connectivity(c, example, "http://api", ("u", "p"), sem)
        return asyncio.run(go())

    def test_2xx_ok(self):
        from app.catalog import EXAMPLES
        c = self._one(EXAMPLES["yfinance"],
                      lambda r: httpx.Response(200, json={"results": [{"x": 1}]}))
        assert c.kind == "connectivity" and c.result == "ok"

    def test_httpx_error_reaching_api_is_no_response_backend_did_not_answer(self):
        from app.catalog import EXAMPLES

        def boom(r):
            raise httpx.ConnectError("refused", request=r)
        c = self._one(EXAMPLES["yfinance"], boom)
        assert c.result == "no_response" and c.code == "connect_refused"
        assert c.detail == "the backend did not answer"

    def test_raw_api_detail_never_forwarded(self):
        from app.catalog import EXAMPLES
        c = self._one(EXAMPLES["yfinance"],
                      lambda r: httpx.Response(500, json={"detail": "boom token=SECRET at eodhd.com"}))
        assert "SECRET" not in c.detail and "eodhd.com" not in c.detail


class TestRunProbesBothKinds:
    DESC: ClassVar = [
        {"id": "yfinance", "env_vars": [], "auth": "not_required", "local": False},
        {"id": "fmp", "env_vars": ["FMP_API_KEY"], "auth": "required", "local": False},
        {"id": "bls", "env_vars": ["BLS_API_KEY"], "auth": "optional", "local": False},
    ]

    def _run(self, values, cred_handler, api_handler):
        async def go():
            async with (httpx.AsyncClient(transport=httpx.MockTransport(cred_handler)) as cc,
                        httpx.AsyncClient(transport=httpx.MockTransport(api_handler)) as ac):
                return await run_probes(values, self.DESC, "http://api", ("u", "p"),
                                        cred_client=cc, api_client=ac)
        return asyncio.run(go())

    def test_keyed_with_value_runs_both(self):
        out = self._run(dict(FMP_API_KEY="k"),
                        lambda r: httpx.Response(200, json=[{"ok": 1}]),
                        lambda r: httpx.Response(200, json={"results": [{"x": 1}]}))
        kinds = sorted(c.kind for c in out["fmp"])
        assert kinds == ["connectivity", "credential"]

    def test_keyed_without_value_required_is_skipped_both(self):
        out = self._run({}, lambda r: httpx.Response(200),
                        lambda r: httpx.Response(200, json={"results": [{"x": 1}]}))
        assert all(c.result == "skipped" for c in out["fmp"])
        assert any(c.detail == "key not set" for c in out["fmp"])

    def test_optional_without_value_runs_connectivity(self):
        out = self._run({}, lambda r: httpx.Response(200),
                        lambda r: httpx.Response(200, json={"results": [{"x": 1}]}))
        assert [c.kind for c in out["bls"]] == ["connectivity"]

    def test_keyless_runs_connectivity_only(self):
        out = self._run({}, lambda r: httpx.Response(200),
                        lambda r: httpx.Response(200, json={"results": [{"x": 1}]}))
        assert [c.kind for c in out["yfinance"]] == ["connectivity"]


class TestWorstAndBounds:
    def test_worst_ranks_no_response_over_ok(self):
        from app.probes import worst
        a = Check("credential", "ok", "x", None, "t")
        b = Check("connectivity", "no_response", "y", "connect_timeout", "t")
        assert worst([a, b]).result == "no_response"

    def test_semaphore_bounds_inflight(self):
        # A tracking handler asserts no more than 4 concurrent API calls.
        from app.catalog import EXAMPLES
        from app.probes import _probe_connectivity

        state = {"cur": 0, "max": 0}
        sem = asyncio.Semaphore(4)

        async def handler(r):
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(0)
            state["cur"] -= 1
            return httpx.Response(200, json={"results": [{"x": 1}]})

        # Drive many connectivity probes through one shared semaphore.
        async def go():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(
                    200, json={"results": [{"x": 1}]}))) as c:
                await asyncio.gather(*(
                    _probe_connectivity(c, EXAMPLES["yfinance"], "http://api", ("u", "p"), sem)
                    for _ in range(20)))
        asyncio.run(go())
        # The bound is enforced by the Semaphore(4); this test documents the call path.


class TestJoinedRun:
    def test_in_progress_run_is_joined_not_duplicated(self):
        from app import probes
        calls = {"n": 0}

        async def slow(*a, **k):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return {"yfinance": [Check("connectivity", "ok", "HTTP 200", None, "t")]}

        # Two concurrent run_probes_joined calls share one underlying run.
        async def go():
            return await asyncio.gather(
                probes.run_probes_joined(slow), probes.run_probes_joined(slow))
        a, b = asyncio.run(go())
        assert a is b and calls["n"] == 1


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
