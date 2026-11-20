# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed daily-price routes from the public HTTP boundary."""
from copy import deepcopy
import unittest
from unittest.mock import MagicMock, call, patch


HISTORY = ("equity/price/historical", "etf/historical")
PREFIX = "/api/v1/eodhd/"
SYMBOLS = ["MCD.US", "AAPL.US"]
BOUNDS = {"start_date": "2026-10-12", "end_date": "2026-11-19"}
PARAMS = {"provider": "eodhd", "interval": "1d", "symbol": ",".join(SYMBOLS), **BOUNDS}
BAR = {"date": "2026-10-12", "open": 100, "high": 110, "low": 97,
       "close": 105, "adjusted_close": 104, "volume": 1000}


def sdk_call(symbol, period="d"):
    return call(symbol=symbol, period=period, from_date=BOUNDS["start_date"],
                to_date=BOUNDS["end_date"], order="a")


def source_envelope(body):
    return (body.get("extra", {}).get("results_metadata") or {}).get("chart_sources")


class InstalledDailyPrice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from openbb_core.app.model.credentials import Credentials
        from openbb_core.app.model.user_settings import UserSettings
        from openbb_core.app.service.user_service import UserService
        from openbb_platform_api.main import app

        settings = UserSettings.model_construct(credentials=Credentials(eodhd_api_key="TEST_KEY"))
        cls.enterClassContext(patch.object(UserService, "read_from_file", staticmethod(lambda: settings)))
        cls.client = cls.enterClassContext(TestClient(app))

    def setUp(self):
        sdk = MagicMock()
        self.daily = sdk.get_eod_historical_stock_market_data
        self.daily.side_effect = lambda **_: deepcopy([BAR])
        self.enterContext(patch("openbq_eodhd.models._bars.get_client", return_value=sdk))

    def get(self, route, **params):
        return self.client.get(PREFIX + route, params={**PARAMS, **params})

    def test_mirror_widgets_and_openapi_advertise_the_wire_contract(self):
        from openbq_eodhd import eodhd_provider

        schema = self.client.get("/openapi.json").json()["paths"]
        widgets = self.client.get("/widgets.json").json()
        for route, model in zip(HISTORY, ("EquityHistorical", "EtfHistorical"), strict=True):
            with self.subTest(route=route):
                self.assertNotIn("/api/v1/" + route, schema)
                self.assertIs(eodhd_provider.fetcher_dict[model], eodhd_provider.fetcher_dict["Eodhd" + model])
                parameters = {p["name"]: p["schema"] for p in schema[PREFIX + route]["get"]["parameters"]}
                self.assertIn("chart_source", parameters)
                self.assertEqual(parameters["chart_source"]["type"], "boolean")
                self.assertIs(parameters["chart_source"]["default"], False)
                widget = widgets["eodhd_" + route.replace("/", "_") + "_eodhd_obb"]
                self.assertEqual(widget["endpoint"], PREFIX + route)
                self.assertEqual(widget["data"]["dataKey"], "results")
                fields = {parameter["paramName"]: parameter for parameter in widget["params"]}
                self.assertTrue({"chart_source", "provider", "symbol", "start_date", "end_date", "interval"} <= fields.keys())
                self.assertIs(fields["chart_source"]["value"], False)

    def test_each_mirror_performs_one_bounded_sdk_call_per_listing(self):
        mirror_rows = []
        for route in HISTORY:
            with self.subTest(route=route):
                wanted_calls = [sdk_call(symbol) for symbol in SYMBOLS]
                self.daily.reset_mock()
                opted_in = self.get(route, chart_source="true")
                self.assertEqual(opted_in.status_code, 200, opted_in.text)
                self.assertEqual(self.daily.call_args_list, wanted_calls)
                body = opted_in.json()
                self.assertEqual(body["provider"], "eodhd")
                rows = body["results"]
                self.assertEqual([(r["symbol"], r["date"], r["adjusted_close"]) for r in rows],
                                 [(symbol, BAR["date"], BAR["adjusted_close"]) for symbol in sorted(SYMBOLS)])
                mirror_rows.append(rows)
                envelope = source_envelope(body)
                self.assertIsNotNone(envelope, body)
                self.assertEqual(set(envelope), {"version", "receipts"})
                self.assertEqual(envelope["version"], 1)
                receipt, = envelope["receipts"]
                self.assertEqual(receipt["kind"], "daily-price")
                self.assertEqual(receipt["symbols"], SYMBOLS)
                self.assertEqual({key: receipt[key] for key in BOUNDS}, BOUNDS)
                self.assertEqual((receipt["interval"], receipt["date_field"], receipt["price_field"],
                                  receipt["symbol_field"]), ("1d", "date", "adjusted_close", "symbol"))
                self.assertEqual((receipt["raw_count"], receipt["normalized_count"], receipt["delivered_count"]),
                                 (len(rows), len(rows), len(rows)))
                self.assertEqual(receipt["listings"], [
                    {"symbol": symbol, "raw_count": 1, "normalized_count": 1, "delivered_count": 1,
                     "duplicate_count": 0, "omissions": []}
                    for symbol in SYMBOLS
                ])
                self.assertFalse(any(receipt["unsafe"].values()))
                self.daily.reset_mock()
                plain = self.get(route)
                self.assertEqual(plain.status_code, 200, plain.text)
                self.assertEqual(self.daily.call_args_list, wanted_calls)
                self.assertIsNone(source_envelope(plain.json()))
                self.assertEqual(rows, plain.json()["results"])
        if len(mirror_rows) == len(HISTORY):
            self.assertEqual(*mirror_rows)

    def test_empty_array_preserves_plain_204_and_returns_counted_opt_in_200(self):
        self.daily.side_effect = None
        self.daily.return_value = []
        for route in HISTORY:
            with self.subTest(route=route):
                self.daily.reset_mock()
                empty = self.get(route, symbol="AAPL.US", chart_source="true")
                self.assertEqual(empty.status_code, 200, empty.text)
                self.daily.assert_called_once_with(**sdk_call("AAPL.US").kwargs)
                body = empty.json()
                self.assertEqual(body["results"], [])
                receipt, = source_envelope(body)["receipts"]
                self.assertEqual(receipt["raw_count"], 0)
                self.assertEqual(receipt["delivered_count"], 0)
                self.assertIsNone(receipt["symbol_field"])
                self.daily.reset_mock()
                plain = self.get(route, symbol="AAPL.US")
                self.assertEqual(plain.status_code, 204, plain.text)
                self.assertEqual(plain.content, b"")
                self.daily.assert_called_once_with(**sdk_call("AAPL.US").kwargs)

    def test_unsupported_acquisitions_produce_no_chart_evidence(self):
        requests = [
            (HISTORY[0], "SHEL.LSE", "1d"),
            (HISTORY[1], "VTI.US", "1W"),
            ("crypto/price/historical", "BTC-USD.CC", "1d"),
            ("currency/price/historical", "EURUSD.FOREX", "1d"),
            ("index/price/historical", "GSPC.INDX", "1d"),
        ]
        for route, symbol, interval in requests:
            with self.subTest(route=route, symbol=symbol, interval=interval):
                self.daily.reset_mock()
                result = self.get(route, symbol=symbol, interval=interval, chart_source="true")
                self.assertEqual(result.status_code, 200, result.text)
                self.assertTrue(result.json()["results"])
                self.assertIsNone(source_envelope(result.json()))
                self.daily.assert_called_once_with(**sdk_call(symbol, "w" if interval == "1W" else "d").kwargs)
