# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbq-eodhd on this line's ODP: the locked packages, the provider-fixes
overlay and no standard routers (openbb-equity and friends are not installed).

Run where openbq-eodhd is installed on the locked recipe, with the overlay
applied and the static package rebuilt (the Dockerfile's api image does all three;
v9/eodhd/verify.py runs this module at build time):

    python -m unittest discover -s v9/eodhd/tests

No EODHD key and no network: the SDK boundary (get_client) is replaced with a
stub that returns tests/fixtures/eod_bars.json (fictional values).
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
        self.assertEqual(len(self.mirrors), 52)
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
        self.assertEqual(out["eodhd"], 52)


if __name__ == "__main__":
    unittest.main()
