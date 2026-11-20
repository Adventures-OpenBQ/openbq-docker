# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbq-eodhd on this line's ODP: the locked packages, the provider-fixes
overlay and no standard routers (openbb-equity and friends are not installed).

Run where openbq-eodhd is installed on the locked recipe, with the overlay
applied and the static package rebuilt (the Dockerfile's api image does all three;
v9/eodhd/verify.py runs this module at build time):

    python -m unittest discover -s v9/eodhd/tests

No EODHD key and no network: SDK calls return fictional prices and statements.
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")

# The EODHD app's cards, in openbq_eodhd/assets/apps.json order.
EODHD_APP_WIDGETS = [
    "eodhd_equity_profile_eodhd_obb",
    "eodhd_equity_price_quote_eodhd_obb",
    "eodhd_equity_price_historical_eodhd_obb",
    "eodhd_equity_fundamental_income_eodhd_obb",
    "eodhd_equity_fundamental_dividends_eodhd_obb",
    "eodhd_equity_ownership_institutional_eodhd_obb",
    "eodhd_fixedincome_government_yield_curve_eodhd_obb",
    "eodhd_index_price_historical_eodhd_obb",
]


def _run(code: str, **env: str) -> dict:
    """Run `code` in a fresh interpreter (its own Env and app); return its JSON."""
    full_env = {**os.environ, **env}
    for name in ("OPENBB_API_AUTH", "OPENBB_API_USERNAME", "OPENBB_API_PASSWORD"):
        if name not in env:
            full_env.pop(name, None)
    run = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=full_env, capture_output=True, text=True, timeout=900, check=False,
    )
    if run.returncode:
        raise AssertionError(run.stderr[-4000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


def _mirrors() -> dict[str, str]:
    """Mirror path -> model, for every MIRRORS row this extension has a fetcher for."""
    from openbq_eodhd import eodhd_provider
    from openbq_eodhd.eodhd_router import MIRRORS

    return {
        MIRRORS[k][0]: f"Eodhd{k}"
        for k in eodhd_provider.fetcher_dict
        if k in MIRRORS
    }


class MirrorNamespace(unittest.TestCase):
    """Without the standard routers, obb.eodhd.* is where EODHD data is routed."""

    @classmethod
    def setUpClass(cls):
        from openbb_core.api.rest_api import app
        from openbb_core.app.router import CommandMap
        from openbb_platform_api.utils.widgets import build_json

        cls.mirrors = _mirrors()
        cls.paths = app.openapi()["paths"]
        cls.models = CommandMap().commands_model
        cls.widgets = build_json(app.openapi(), [])

    def test_every_mirror_is_mounted_with_its_own_model(self):
        self.assertEqual(len(self.mirrors), 53)
        self.assertIn("/api/v1/eodhd/equity/estimates/earnings_vs_estimates", self.paths)
        for path, model in self.mirrors.items():
            self.assertIn("/api/v1/eodhd" + path, self.paths)
            self.assertEqual(self.models["/eodhd" + path], model)

    def test_every_mirror_offers_only_eodhd(self):
        for path in self.mirrors:
            op = self.paths["/api/v1/eodhd" + path]["get"]
            prov = next(p for p in op["parameters"] if p["name"] == "provider")
            schema = prov["schema"]
            self.assertEqual(schema.get("enum") or [schema.get("const")], ["eodhd"], path)

    def test_no_eodhd_route_outside_the_namespace(self):
        # No standard routers on this line: provider=eodhd has no other home.
        stray = [m for p, m in self.models.items() if m.startswith("Eodhd") and not p.startswith("/eodhd/")]
        self.assertEqual(stray, [])

    def test_every_mirror_is_a_widget(self):
        for path in self.mirrors:
            wid = "eodhd_" + path.strip("/").replace("/", "_") + "_eodhd_obb"
            self.assertIn(wid, self.widgets)
            self.assertEqual(self.widgets[wid]["endpoint"], "/api/v1/eodhd" + path)

    def test_screener_widget_formats_five_day_change_as_a_fractional_percent(self):
        widget = self.widgets["eodhd_equity_screener_eodhd_obb"]
        columns = {c["field"]: c for c in widget["data"]["table"]["columnsDefs"]}
        self.assertIn("price_change_5d", columns)
        self.assertEqual(columns["price_change_5d"]["formatterFn"], "normalizedPercent")
        self.assertEqual(columns["currency_symbol"]["cellDataType"], "text")

    def test_app_cards_are_served_widgets(self):
        for wid in EODHD_APP_WIDGETS:
            self.assertIn(wid, self.widgets)


class StubbedQuery(unittest.TestCase):
    def test_historical_prices_from_the_saved_bars(self):
        out = _run(
            f"""
            import json
            from unittest.mock import MagicMock, patch
            from fastapi.testclient import TestClient
            from openbb_core.api.rest_api import app

            bars = json.load(open({str(FIXTURES / "eod_bars.json")!r}))
            client = MagicMock()
            client.__enter__.return_value = client
            client.get_eod_historical_stock_market_data.return_value = bars
            with patch("openbq_eodhd.models._bars.get_client", return_value=client):
                r = TestClient(app).get(
                    "/api/v1/eodhd/equity/price/historical",
                    params={{"symbol": "AAPL", "start_date": "2025-01-01", "end_date": "2025-01-07"}},
                )
            call = client.get_eod_historical_stock_market_data.call_args.kwargs
            print(json.dumps({{"status": r.status_code, "body": r.json(), "symbol": call["symbol"]}}))
            """,
            **{"EODHD_API_KEY": "PLACEHOLDER"},
        )
        self.assertEqual(out["status"], 200, out["body"])
        self.assertEqual(out["symbol"], "AAPL.US")
        rows = out["body"]["results"]
        # The no-trade bar (null OHLC) is dropped; adjusted_close is kept.
        self.assertEqual([r["close"] for r in rows], [102.0, 104.0])
        self.assertEqual(rows[0]["adjusted_close"], 101.5)
        self.assertEqual(out["body"]["provider"], "eodhd")

    def test_missing_key_is_not_a_server_error(self):
        out = _run(
            """
            import json
            from fastapi.testclient import TestClient
            from openbb_core.api.rest_api import app

            r = TestClient(app).get("/api/v1/eodhd/equity/price/historical", params={"symbol": "AAPL"})
            print(json.dumps({"status": r.status_code}))
            """,
            **{"EODHD_API_KEY": ""},
        )
        self.assertNotEqual(out["status"], 200)
        self.assertLess(out["status"], 500)


class ChartSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.responses = _run(
            """
            import json
            from unittest.mock import MagicMock, patch

            from fastapi.testclient import TestClient
            from openbb_core.api.rest_api import app

            sdk = MagicMock()
            sdk.__enter__.return_value = sdk
            sdk.stock_market_screener.return_value = {"data": [{
                "code": "AAPL", "exchange": "US", "name": "Apple Inc.",
                "last_day_data_date": "2026-08-28", "refund_5d_p": 5,
                "dividend_yield": 0.004, "market_capitalization": 1000000000,
                "currency_symbol": "$",
            }]}
            sdk.get_historical_dividends_data.side_effect = [
                [], [], [
                    {"date": "2026-02-12", "value": 0.2, "unadjustedValue": 0.8,
                     "currency": "GBP", "period": "Special"},
                    {"date": "2026-05-12", "value": None, "unadjustedValue": 987654.321,
                     "currency": "USD", "period": "Quarterly"},
                    {"date": "2026-06-31", "value": 0.5, "currency": "GBP"},
                ],
            ]
            sdk.get_fundamentals_data.return_value = {
                "General": {"CurrencyCode": "GBX", "FiscalYearEnd": "June"},
                "Financials": {"Income_Statement": {
                    "currency_symbol": "USD",
                    "yearly": {"2026-06-30": {
                        "date": "2026-06-30", "currency_symbol": "USD",
                        "totalRevenue": "100", "costOfRevenue": "40", "grossProfit": "60",
                        "operatingIncome": "30", "incomeBeforeTax": "25",
                        "incomeTaxExpense": "5", "netIncome": "20",
                    }},
                }},
            }

            def get(client, path, **params):
                response = client.get(f"/api/v1/eodhd/equity/{path}", params=params)
                return [response.status_code, response.json() if response.content else None]

            bounds = {"symbol": "SHEL.LSE", "start_date": "2026-01-01", "end_date": "2026-06-30"}
            income = {"symbol": "HSBA.LSE", "period": "annual", "limit": 1}
            with (
                patch("openbq_eodhd.models._client.get_client", return_value=sdk),
                patch("openbq_eodhd.models.corporate_actions.get_client", return_value=sdk),
                patch("openbq_eodhd.models._fundamentals.get_client", return_value=sdk),
                TestClient(app) as client,
            ):
                responses = {
                    "screener": get(client, "screener", exchange="us", chart_source=True),
                    "legacy_screener": get(client, "screener", exchange="us"),
                    "empty_dividends": get(client, "fundamental/dividends", chart_source=True, **bounds),
                    "legacy_empty_dividends": get(client, "fundamental/dividends", **bounds),
                    "unsafe_dividends": get(client, "fundamental/dividends", chart_source=True, **bounds),
                    "income": get(client, "fundamental/income", chart_source=True, **income),
                    "legacy_income": get(client, "fundamental/income", **income),
                }
            responses["sdk_calls"] = [
                sdk.stock_market_screener.call_count,
                sdk.get_historical_dividends_data.call_count,
                sdk.get_fundamentals_data.call_count,
            ]
            print(json.dumps(responses))
            """,
            **{"EODHD_API_KEY": "PLACEHOLDER"},
        )

    def body(self, name):
        status, body = self.responses[name]
        self.assertEqual(status, 200, body)
        return body

    @staticmethod
    def select(body, dotted_path):
        for key in dotted_path.split("."):
            body = body[key]
        return body

    def receipt(self, body, kind, raw_count, delivered_count):
        path = "extra.results_metadata.chart_evidence"
        self.assertIn("chart_evidence", body.get("extra", {}).get("results_metadata", {}))
        receipt = self.select(body, path)
        self.assertEqual(receipt["version"], 1)
        self.assertEqual(receipt["kind"], kind)
        self.assertEqual(receipt["raw_count"], raw_count)
        self.assertEqual(receipt["normalized_count"], delivered_count)
        self.assertEqual(receipt["delivered_count"], delivered_count)
        return receipt

    def test_screener_rows_and_receipt_have_separate_selectors_in_the_same_envelope(self):
        body = self.body("screener")
        rows = self.select(body, "results")
        self.assertEqual(len(rows), 1)
        self.assertIn("price_change_5d", rows[0])
        self.assertEqual(rows[0]["price_change_5d"], 0.05)
        self.assertEqual(rows[0]["dividend_yield"], 0.004)
        self.assertEqual(rows[0]["market_cap"], 1000000000)
        self.assertEqual(rows[0]["currency_symbol"], "$")
        receipt = self.receipt(body, "screener", 1, 1)
        self.assertEqual(receipt["scope"]["filters"], [["exchange", "=", "us"]])
        self.assertEqual(receipt["cohorts"][0]["price_date"], "2026-08-28")
        self.assertEqual(receipt["cohorts"][0]["denominations"], ["USD"])
        self.assertEqual(receipt["units"]["price_change_5d"], "fraction")

    def test_empty_dividend_source_preserves_unknown_coverage(self):
        body = self.body("empty_dividends")
        self.assertEqual(self.select(body, "results"), [])
        receipt = self.receipt(body, "dividends", 0, 0)
        self.assertEqual(receipt["coverage"], {"status": "unknown"})
        self.assertEqual(receipt["qualified_symbol"], "SHEL.LSE")
        self.assertEqual(receipt["requested_start"], "2026-01-01")
        self.assertEqual(receipt["requested_end"], "2026-06-30")
        self.assertEqual(receipt["event_dates"], [])

    def test_unsafe_dividend_evidence_survives_row_normalization(self):
        body = self.body("unsafe_dividends")
        receipt = self.receipt(body, "dividends", 3, 1)
        self.assertEqual(receipt["coverage"], {"status": "unknown"})
        self.assertEqual(receipt["amount_basis"], "split-adjusted-current-share")
        self.assertEqual(receipt["event_dates"], ["2026-02-12", "2026-05-12"])
        self.assertEqual(receipt["invalid_amount_dates"], ["2026-05-12"])
        self.assertEqual(receipt["payment_currencies"], ["GBP", "USD"])
        self.assertTrue(receipt["unsafe"]["invalid_ex_date"])
        self.assertTrue(receipt["unsafe"]["currency_conflict"])
        row, = self.select(body, "results")
        self.assertEqual(row["amount"], 0.2)
        self.assertEqual(row["unadjusted_amount"], 0.8)
        self.assertEqual(row["currency"], "GBP")
        self.assertNotIn("987654.321", json.dumps(receipt))

    def test_income_receipt_uses_statement_currency_and_leaves_scale_unknown(self):
        body = self.body("income")
        receipt = self.receipt(body, "income", 1, 1)
        self.assertEqual(receipt["qualified_symbol"], "HSBA.LSE")
        self.assertEqual(receipt["reporting_currency"], "USD")
        self.assertEqual(receipt["scale"], {"status": "unknown"})
        period, = receipt["periods"]
        self.assertEqual(period["period_kind"], "FY")
        self.assertEqual(period["period_end"], "2026-06-30")
        self.assertEqual(period["record_coverage"], "full-record")
        self.assertEqual(self.select(body, "results")[0]["net_income"], 20)

    def test_default_requests_keep_the_legacy_results_envelope(self):
        for source in ("screener", "income"):
            with self.subTest(source=source):
                legacy = self.body("legacy_" + source)
                self.assertNotIn("results_metadata", legacy["extra"])
                row, = self.body(source)["results"]
                if source == "income":
                    self.assertIsNone(row.get("fiscal_year"))
                    row = {**row, "fiscal_year": 2026}
                self.assertEqual(legacy["results"], [row])
        self.assertEqual(self.responses["legacy_empty_dividends"], [204, None])

    def test_opt_in_does_not_add_sdk_requests(self):
        self.assertEqual(self.responses["sdk_calls"], [2, 3, 1])


class Catalogs(unittest.TestCase):
    def test_openbb_api_serves_the_eodhd_app(self):
        # openbb-api merges router-attached apps.json endpoints into /apps.json
        # and drops an app unless its cards are served widgets.
        out = _run(
            """
            import json, sys
            sys.argv = ["openbb-api"]
            from fastapi.testclient import TestClient
            from openbb_platform_api.app.app import app

            c = TestClient(app)
            apps = c.get("/apps.json").json()
            own = c.get("/api/v1/eodhd/apps.json").json()
            eodhd = [a for a in apps if a.get("name") == "EODHD"]
            cards = [w["i"] for a in eodhd for t in a["tabs"].values() for w in t["layout"]]
            print(json.dumps({"count": len(eodhd), "cards": cards, "own": len(own)}))
            """,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["own"], 1)
        self.assertEqual(out["cards"], EODHD_APP_WIDGETS)


class ApiAuth(unittest.TestCase):
    def test_rest_app_builds_under_api_auth(self):
        # The donor's scripts/patch_openbb_core_auth.py (cd0aaeb) exists because
        # stock openbb-core 2.0.1 cannot build this app with OPENBB_API_AUTH=true.
        # provider-fixes/openbb_core/api/router/commands.py carries both of its
        # edits; this pins that the overlay covers the eodhd mirrors too.
        out = _run(
            """
            import json
            from openbb_core.api.rest_api import app
            paths = app.openapi()["paths"]
            print(json.dumps({"eodhd": sum(p.startswith("/api/v1/eodhd/") for p in paths)}))
            """,
            OPENBB_API_AUTH="true", OPENBB_API_USERNAME="check", OPENBB_API_PASSWORD="check",
        )
        self.assertEqual(out["eodhd"], 53)


if __name__ == "__main__":
    unittest.main()
