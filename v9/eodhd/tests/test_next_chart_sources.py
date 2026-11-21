# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Qualify the installed mirror routes on this routers-less ODP image."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class NextChartSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from openbb_core.api.rest_api import app
        from openbb_core.app.model.credentials import Credentials
        from openbb_core.app.model.user_settings import UserSettings
        from openbb_core.app.service.user_service import UserService

        cls.enterClassContext(patch.object(UserService, "read_from_file", return_value=UserSettings.model_construct(
            credentials=Credentials(eodhd_api_key="demo"))))
        cls.client = cls.enterClassContext(TestClient(app))

    def get(self, route, **params):
        response = self.client.get("/api/v1/eodhd/" + route, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def receipt(self, body, kind):
        metadata = body.get("extra", {}).get("results_metadata", {})
        self.assertIn("chart_sources", metadata)
        envelope = metadata["chart_sources"]
        self.assertEqual(envelope["version"], 1)
        self.assertEqual([r["kind"] for r in envelope["receipts"]], [kind])
        receipt, = envelope["receipts"]
        self.assertEqual(receipt["delivered_count"], len(body["results"]))
        return receipt

    def test_generated_routes_advertise_opt_in_only_for_supported_acquisitions(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        def params(route):
            return {p["name"] for p in paths["/api/v1/eodhd/" + route]["get"]["parameters"]}
        for route in ["news/company", "equity/ownership/share_statistics", "equity/fundamental/metrics",
                      "equity/fundamental/ratios", "etf/holdings",
                      "equity/price/historical", "etf/historical"]:
            with self.subTest(route=route):
                self.assertIn("chart_source", params(route))
        for route in ["equity/price/quote", "equity/estimates/consensus",
                      "crypto/price/historical", "currency/price/historical", "index/price/historical"]:
            with self.subTest(route=route):
                self.assertNotIn("chart_source", params(route))

    def test_news_page_preserves_legacy_and_exposes_original_day_and_zero_polarity(self):
        article = {"date": "2024-03-01T00:45:00+01:00", "title": "Example", "link": "https://example.com/news",
                   "symbols": ["AAPL.US"], "sentiment": {"polarity": 0}}
        with patch("openbq_eodhd.models.news.rest_json", return_value=[article]) as upstream:
            plain = self.get("news/company", symbol="AAPL")
            chart = self.get("news/company", symbol="AAPL", chart_source="true")
        self.assertEqual(upstream.call_count, 2)
        self.assertNotIn("polarity", plain["results"][0])
        self.assertNotIn("chart_sources", plain.get("extra", {}).get("results_metadata", {}))
        evidence = self.receipt(chart, "news")
        self.assertEqual(evidence["scope"], {"kind": "sample", "start": None, "end": None, "offset": 0, "limit": 50})
        self.assertEqual(evidence["coordinates"], [
            {"article_id": article["link"], "utc_day": "2024-02-29", "scored": True}])
        self.assertEqual(chart["results"][0]["polarity"], 0)

    def test_cached_common_stock_and_etf_use_original_acquisition_and_refuse_legacy_vintage(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock

        import pandas as pd
        from openbq_eodhd.models import _fundamentals as cache

        stock = {"General": {"Code": "AAPL", "PrimaryTicker": "AAPL.US", "Type": "Common Stock",
                             "Exchange": "NASDAQ", "UpdatedAt": "2024-03-01"},
                 "SharesStats": {"PercentInsiders": 1.625, "PercentInstitutions": 67.5},
                 "Highlights": {"DividendYield": 0, "PERatio": 19.875}}
        fund = {"General": {"Code": "VTI", "Exchange": "NYSE ARCA", "CountryISO": "US", "Type": "ETF"},
                "ETF_Data": {"Holdings": {"AAPL.US": {"Code": "AAPL", "Exchange": "US", "Sector": "Technology",
                                                       "Assets_%": 6.25}}}}
        retrieved = datetime.now(timezone.utc) - timedelta(minutes=5)
        stamp = retrieved.isoformat().replace("+00:00", "Z")
        metadata = {"retrieved_at": retrieved.isoformat(), "fetched_at": datetime.now(timezone.utc).isoformat()}
        def read(symbol):
            payload = {"AAPL.US": stock, "VTI.US": fund}[symbol]
            return SimpleNamespace(data=pd.DataFrame({"payload": [json.dumps(payload)]}), metadata=metadata.copy())
        library = Mock()
        library.has_symbol.return_value = True
        library.read.side_effect = read
        library.read_metadata.side_effect = read
        routes = [("equity/ownership/share_statistics", "AAPL", "ownership"),
                  ("equity/fundamental/metrics", "AAPL", "metric"), ("equity/fundamental/ratios", "AAPL", "metric"),
                  ("etf/holdings", "VTI", "etf-hierarchy")]
        with patch.object(cache, "_arctic_library", return_value=library), patch.object(cache, "_fetch_sync") as upstream:
            self.addCleanup(cache._reset_cache_for_tests)
            for route, symbol, kind in routes:
                with self.subTest(route=route):
                    cache._reset_cache_for_tests()
                    plain = self.get(route, symbol=symbol)
                    self.assertNotIn("chart_sources", plain.get("extra", {}).get("results_metadata", {}))
                    self.assertNotIn("metric_vintage", plain["results"][0])
                    self.assertNotIn("snapshot", plain["results"][0])
                    chart = self.get(route, symbol=symbol, chart_source="true")
                    receipt = self.receipt(chart, kind)
                    self.assertEqual(receipt["retrieved_at"], stamp)
                    row = chart["results"][0]
                    if kind == "metric":
                        self.assertEqual(set(receipt["metrics"]), {"dividend_yield", "pe_ratio"})
                        self.assertEqual((row["metric_vintage"], row["dividend_yield"], row["pe_ratio"]), (stamp, 0, 19.875))
                        self.assertIsNone(receipt["metrics"]["pe_ratio"]["as_of"])
                    elif kind == "ownership":
                        self.assertEqual(receipt["partition"], {"status": "unavailable"})
                        self.assertEqual((row["symbol"], row["percent_insiders"]), ("AAPL.US", 1.625))
                    else:
                        self.assertEqual((receipt["coverage"], receipt["missing_mass"]), ("unknown", {"status": "unknown"}))
                        self.assertEqual((row["symbol"], row["weight"], row["snapshot"]), ("AAPL.US", 0.0625, stamp))
            del metadata["retrieved_at"]
            for route, symbol, _ in routes:
                with self.subTest(legacy_cache=route):
                    cache._reset_cache_for_tests()
                    body = self.get(route, symbol=symbol, chart_source="true")
                    self.assertTrue(body["results"])
                    self.assertNotIn("chart_sources", body.get("extra", {}).get("results_metadata", {}))
            upstream.assert_not_called()
