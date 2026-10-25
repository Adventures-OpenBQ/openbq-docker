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

ROUTE = "/api/v1/econdb/economy/indicators"
SERIES = [{
    "ticker": "RGDPUS", "description": "Real gross domestic product", "geography": "United States",
    "frequency": "Q", "dataset": "BEA_NIPA",
    "data": {"dates": ["2024-01-01", "2024-04-01"], "values": [23115976, 23320074]},
}]


class EconDbTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        async def token(use_cache=True):
            self.calls.append("token")
            return "TEMP"

        async def request(url, response_callback=None, **kwargs):
            self.calls.append(url)

            class Response:
                status, reason = 200, "OK"

                async def json(self):
                    return {"results": SERIES, "next": None}

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


if __name__ == "__main__":
    unittest.main()
