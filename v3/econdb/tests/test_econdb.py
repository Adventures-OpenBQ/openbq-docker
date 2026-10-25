# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The ported EconDB provider through the real ODP app, with EconDB's HTTP answers stubbed.

Needs openbb-core 2.0.1 and openbb-econdb installed (the image runs these through
v3/econdb/verify.py, with unittest, since the image has no pytest). No network.
"""
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from openbb_core.api.rest_api import app
from openbb_econdb.utils import helpers
from openbb_platform_api.utils.widgets import build_json
from openbb_core.provider.utils.errors import OpenBBError, UnauthorizedError

real_create_token = helpers.create_token

ROUTE = "/api/v1/econdb/economy/indicators"
SERIES = [{
    "ticker": "RGDPUS", "description": "Real gross domestic product", "geography": "United States",
    "frequency": "Q", "dataset": "BEA_NIPA",
    "data": {"dates": ["2024-01-01", "2024-04-01"], "values": [23115976, 23320074]},
}]


class EconDbTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.response_status = 200
        self.response_payload = {"results": SERIES, "next": None}

        async def token(use_cache=True):
            self.calls.append("token")
            return "TEMP"

        async def request(url, response_callback=None, **kwargs):
            self.calls.append(url)
            status, payload = self.response_status, self.response_payload

            class Response:
                reason = "Upstream response"

                async def json(self):
                    return payload

            Response.status = status
            return await response_callback(Response(), None)

        for name, stub in (("create_token", token), ("amake_request", request)):
            patcher = mock.patch.object(helpers, name, stub)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_indicators_need_no_key_and_return_rows(self):
        r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP", "country": "US",
                                           "start_date": "2024-01-01", "use_cache": False})
        self.assertEqual(r.status_code, 200, r.text)
        rows = r.json()["results"]
        self.assertEqual([(x["date"], x["symbol"], x["country"], x["value"]) for x in rows], [
            ("2024-01-01", "RGDPUS", "United States", 23115976),
            ("2024-04-01", "RGDPUS", "United States", 23320074),
        ])
        self.assertEqual(self.calls[0], "token")  # no key set: a temporary token is asked for
        self.assertIn("ticker=%5BRGDPUS%5D", self.calls[1])
        self.assertIn("token=TEMP", self.calls[1])

    def test_frequency_none_from_the_standard_parameter_is_the_default(self):
        from openbb_econdb.models.economic_indicators import EconDbEconomicIndicatorsQueryParams

        query = EconDbEconomicIndicatorsQueryParams(symbol="RGDP", country="US", frequency=None)
        self.assertEqual(query.frequency, "quarter")

    def test_upstream_unauthorized_is_not_reported_as_empty_data(self):
        self.response_status = 401
        self.response_payload = {"detail": "Unauthorized"}
        r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP", "country": "US", "use_cache": False})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertIn("HTTP 401", r.text)

    def test_refused_temporary_token_returns_a_gateway_error(self):
        self.response_status = 403
        self.response_payload = {"code": "access_denied"}
        with mock.patch.object(helpers, "create_token", real_create_token):
            r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP", "country": "US", "use_cache": False})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertIn("HTTP 403", r.text)

    def test_unrecognized_series_response_is_not_empty_data(self):
        self.response_payload = {"detail": "Service unavailable"}
        r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP", "country": "US", "use_cache": False})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("series response", r.text)

    def test_a_valid_empty_series_response_stays_empty_data(self):
        self.response_payload = {"results": [], "next": None}
        r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP", "country": "US", "use_cache": False})
        self.assertEqual(r.status_code, 204)

    def test_a_symbol_without_a_country_is_a_client_error(self):
        r = self.client.get(ROUTE, params={"provider": "econdb", "symbol": "RGDP"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Valid countries for 'RGDP'", r.text)

    def test_widgets_are_econdb_namespaced_and_keyless(self):
        widgets = build_json(app.openapi(), [])
        self.assertEqual(sorted(k for k in widgets if k.endswith("_econdb_obb")), [
            "econdb_economy_available_indicators_econdb_obb",
            "econdb_economy_country_profile_econdb_obb",
            "econdb_economy_indicators_econdb_obb",
        ])
        self.assertFalse([k for k in widgets if k.startswith("econdb_") and not k.endswith("_econdb_obb")],
                         "an econdb route offers another provider")
        w = widgets["econdb_economy_indicators_econdb_obb"]
        self.assertEqual((w["endpoint"], w["type"]), (ROUTE, "table"))
        self.assertLessEqual({"symbol", "country", "start_date", "end_date", "transform"},
                             {p["paramName"] for p in w["params"]})


class TemporaryTokenTests(unittest.IsolatedAsyncioTestCase):
    async def token(self, status, payload):
        async def request(url, response_callback, **kwargs):
            class Response:
                async def json(self):
                    return payload
            Response.status = status
            return await response_callback(Response(), None)
        with mock.patch.object(helpers, "amake_request", request):
            return await helpers.create_token(use_cache=False)

    async def test_refused_temporary_token_is_an_explicit_error(self):
        with self.assertRaisesRegex(UnauthorizedError, "HTTP 403"):
            await self.token(403, {"code": "access_denied"})

    async def test_missing_temporary_token_is_an_explicit_error(self):
        with self.assertRaisesRegex(OpenBBError, "usable API key"):
            await self.token(200, {})

    async def test_valid_temporary_token_still_works(self):
        self.assertEqual(await self.token(200, {"api_key": "EXAMPLE_TOKEN"}), "EXAMPLE_TOKEN")


if __name__ == "__main__":
    unittest.main()
