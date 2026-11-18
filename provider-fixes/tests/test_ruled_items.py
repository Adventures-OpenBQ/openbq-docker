# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Items ruled on after the v4/v5 regression of 2026-11-18."""
import asyncio
import json
import unittest
from datetime import date, timedelta
from unittest import mock


class TreasuryPricesSessionTokenTest(unittest.TestCase):
    def test_the_download_carries_the_forms_token_on_the_same_session(self):
        from openbb_government_us.treasury.models import treasury_prices as tp

        calls = []

        class Reply:
            def __init__(self, text):
                self.status_code, self.text, self.encoding = 200, text, "ISO-8859-1"
                self.content = text.encode()

        class FakeSession:
            def get(self, url, **kw):
                calls.append(("GET", url, None))
                return Reply('<input type="hidden" name="_csrf" value="tok-1" />')

            def post(self, url, data=None, **kw):
                calls.append(("POST", url, data))
                return Reply("912797UZ8,MARKET BASED BILL,0.0,11/19/2026,,0.0,99.9,99.9\n")

        query = tp.UsTreasuryPricesQueryParams(date=date(2026, 11, 17))
        with mock.patch("requests.Session", FakeSession):
            body = tp.UsTreasuryPricesFetcher.extract_data(query, None)
        self.assertTrue(body.startswith("912797UZ8"))
        self.assertEqual([c[0] for c in calls], ["GET", "POST"])
        self.assertTrue(calls[0][1].endswith("/selectSecurityPriceDate"))
        self.assertIn("priceDateDay=17&priceDateMonth=11&priceDateYear=2026", calls[1][2])
        self.assertTrue(calls[1][2].endswith("&_csrf=tok-1"))


class StrategySkipsOneSidedExpirationTest(unittest.TestCase):
    def test_straddle_takes_the_next_expiration_when_the_nearest_has_one_strike(self):
        from openbb_core.provider.standard_models.options_chains import OptionsChainsData

        near = date.today() + timedelta(days=14)
        far = date.today() + timedelta(days=16)
        rows = [(near, 825.0, "call")] + [
            (far, strike, kind) for strike in (720.0, 730.0, 740.0) for kind in ("call", "put")
        ]
        chain = OptionsChainsData(
            underlying_symbol=["SPY"] * len(rows),
            underlying_price=[733.0] * len(rows),
            contract_symbol=[f"C{i}" for i in range(len(rows))],
            expiration=[r[0] for r in rows],
            dte=[(r[0] - date.today()).days for r in rows],
            strike=[r[1] for r in rows],
            option_type=[r[2] for r in rows],
            bid=[1.0] * len(rows),
            ask=[1.2] * len(rows),
            last_trade_price=[1.1] * len(rows),
        )
        result = chain.straddle(days=14)
        self.assertEqual(result.loc["Expiration"].iloc[0], far.strftime("%Y-%m-%d"))


class FinraRetiredCardsNotOfferedTest(unittest.TestCase):
    GONE = ("finra_equity_search_finra_obb", "finra_equity_profile_finra_obb")

    def test_search_and_profile_are_absent_from_widgets_and_the_app(self):
        from openbb_core.api.rest_api import app
        from openbb_finra.finra_router import finra_apps
        from openbb_platform_api.utils.widgets import build_json

        widgets = build_json(app.openapi(), [])
        self.assertIn("finra_equity_securities_finra_obb", widgets)
        for name in self.GONE:
            self.assertNotIn(name, widgets)
        apps = asyncio.run(finra_apps())
        dumped = json.dumps(apps)
        for name in ("equity_search_finra_obb", "equity_profile_finra_obb"):
            self.assertNotIn(name, dumped)
        self.assertTrue(all(t["layout"] for a in apps for t in a["tabs"].values()))


if __name__ == "__main__":
    unittest.main()
