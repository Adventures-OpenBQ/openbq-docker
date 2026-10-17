# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
from app.catalog import EXAMPLES, classify

RAW = "connect to eodhd.com failed: Name or service not known; token=SECRET123"


class TestShape:
    def test_one_example_per_expected_provider(self):
        # Every non-local descriptor provider the registry or display map knows.
        expected = {
            "yfinance", "sec", "federal_reserve", "imf", "oecd", "government_us",
            "fmp", "fred", "tiingo", "intrinio", "eia", "congress_gov", "bls",
            "cftc", "econdb", "benzinga", "tradingeconomics", "eodhd",
        }
        assert set(EXAMPLES) == expected

    def test_paths_and_doc_and_demo_ok(self):
        for pid, ex in EXAMPLES.items():
            assert ex.path.startswith("/api/v1/")
            assert ex.doc.startswith("https://")
            assert ex.params.get("provider") == pid
        for pid in ("yfinance", "sec", "federal_reserve", "imf", "oecd", "government_us",
                    "cftc", "econdb", "eia", "congress_gov", "eodhd"):
            assert EXAMPLES[pid].demo_ok is True
        # bls 400s without a key on the real platform (its credential gate,
        # not the fetcher, decides) -- it is keyed like fmp/fred/tiingo/etc.
        for pid in ("fmp", "fred", "tiingo", "intrinio", "benzinga", "tradingeconomics", "bls"):
            assert EXAMPLES[pid].demo_ok is False


class TestClassify:
    def test_2xx_with_results_is_ok(self):
        assert classify(200, {"results": [{"x": 1}]})[0] == "ok"

    def test_2xx_empty_results_is_unexpected_response(self):
        result, code, _ = classify(200, {"results": []})
        assert result == "error" and code == "unexpected_response"

    def test_2xx_missing_results_is_unexpected_response(self):
        assert classify(200, {"nope": 1})[1] == "unexpected_response"

    def test_api_401_is_backend_refused_not_provider_auth(self):
        result, code, detail = classify(401, {"detail": "Unauthorized"})
        assert result == "error" and code == "http_auth"
        assert detail == "the backend refused key-maint's own credentials"

    def test_api_403_is_backend_refused(self):
        assert classify(403, {"detail": "x"})[1] == "http_auth"

    def test_provider_auth_marker_is_auth_failed(self):
        result, code, _ = classify(400, {"detail": "Invalid API key for provider"})
        assert result == "auth_failed" and code == "http_auth"

    def test_missing_credential_marker_is_auth_failed(self):
        # The real OpenBB Platform returns HTTP 400 with this body shape when
        # a required provider credential isn't configured -- a demo
        # deployment using credentials.env.example's defaults hits this for
        # fmp/fred/intrinio/benzinga/tradingeconomics, and it must classify
        # as auth_failed/http_auth, not fall through to the generic
        # error/upstream_error default.
        result, code, _ = classify(
            400,
            {"detail": "Missing credential 'fmp_api_key'. Check https://x to get it."},
        )
        assert result == "auth_failed" and code == "http_auth"

    def test_timeout_marker_is_no_response_connect_timeout(self):
        result, code, _ = classify(500, {"detail": "request timed out"})
        assert result == "no_response" and code == "connect_timeout"

    def test_dns_marker_is_no_response_dns_failure(self):
        assert classify(500, {"detail": "Name or service not known"})[1] == "dns_failure"

    def test_refused_marker_is_connect_refused(self):
        assert classify(500, {"detail": "Connection refused"})[1] == "connect_refused"

    def test_tls_marker_is_tls_error(self):
        assert classify(500, {"detail": "SSL certificate problem"})[1] == "tls_error"

    def test_429_marker_is_rate_limited(self):
        assert classify(429, {"detail": "rate limit exceeded"})[1] == "rate_limited"

    def test_other_non_2xx_is_upstream_error(self):
        result, code, _ = classify(502, {"detail": "bad gateway"})
        assert result == "error" and code == "upstream_error"

    def test_raw_api_detail_never_appears_in_detail(self):
        for status in (401, 400, 500, 502, 200):
            _, _, detail = classify(status, {"detail": RAW})
            assert "SECRET123" not in detail and "eodhd.com" not in detail


class TestCheckExitCodes:
    # NOTE: catalog.httpx and this module's `httpx` are the same module
    # object (a single import cache entry), so monkeypatching
    # `catalog.httpx.Client` also replaces the global `httpx.Client`. A
    # lambda that itself calls `httpx.Client(...)` would therefore call
    # the patched version of itself and recurse forever — capture the real
    # class first and close over that instead.
    def test_all_demo_ok_and_keyed_auth_failed_exits_0(self, monkeypatch):
        import httpx

        from app import catalog

        def handler(request):
            pid = request.url.params.get("provider")
            if catalog.EXAMPLES[pid].demo_ok:
                return httpx.Response(200, json={"results": [{"x": 1}]})
            return httpx.Response(400, json={"detail": "Invalid API key"})

        real_client = httpx.Client
        monkeypatch.setattr(catalog.httpx, "Client",
                            lambda **k: real_client(transport=httpx.MockTransport(handler)))
        assert catalog._check("http://api", "u", "p") == 0

    def test_a_demo_provider_returning_empty_fails(self, monkeypatch):
        import httpx

        from app import catalog

        def handler(request):
            return httpx.Response(200, json={"results": []})  # drift on the demo providers

        real_client = httpx.Client
        monkeypatch.setattr(catalog.httpx, "Client",
                            lambda **k: real_client(transport=httpx.MockTransport(handler)))
        assert catalog._check("http://api", "u", "p") == 1

    def test_a_keyed_provider_returning_ok_passes(self, monkeypatch):
        # Against a deployment with real keys configured, a keyed example
        # (demo_ok=False) legitimately succeeds -- that is not drift.
        import httpx

        from app import catalog

        def handler(request):
            return httpx.Response(200, json={"results": [{"x": 1}]})

        real_client = httpx.Client
        monkeypatch.setattr(catalog.httpx, "Client",
                            lambda **k: real_client(transport=httpx.MockTransport(handler)))
        assert catalog._check("http://api", "u", "p") == 0

    def test_a_keyed_provider_returning_error_fails(self, monkeypatch):
        import httpx

        from app import catalog

        def handler(request):
            pid = request.url.params.get("provider")
            if catalog.EXAMPLES[pid].demo_ok:
                return httpx.Response(200, json={"results": [{"x": 1}]})
            return httpx.Response(502, json={"detail": "bad gateway"})  # a real call broke

        real_client = httpx.Client
        monkeypatch.setattr(catalog.httpx, "Client",
                            lambda **k: real_client(transport=httpx.MockTransport(handler)))
        assert catalog._check("http://api", "u", "p") == 1

    def test_a_demo_ok_provider_returning_auth_failed_fails(self, monkeypatch):
        # demo_ok examples still require ok -- auth_failed is not a pass for
        # them even though it is now a pass for keyed examples.
        import httpx

        from app import catalog

        def handler(request):
            pid = request.url.params.get("provider")
            if catalog.EXAMPLES[pid].demo_ok:
                return httpx.Response(400, json={"detail": "Invalid API key"})
            return httpx.Response(400, json={"detail": "Invalid API key"})

        real_client = httpx.Client
        monkeypatch.setattr(catalog.httpx, "Client",
                            lambda **k: real_client(transport=httpx.MockTransport(handler)))
        assert catalog._check("http://api", "u", "p") == 1
