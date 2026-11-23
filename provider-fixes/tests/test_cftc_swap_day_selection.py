# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Swap default dates and limits are chosen after real priceability gates."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


class SwapDaySelectionTest(unittest.TestCase):
    def setUp(self):
        from openbb_cftc.models import swap_trades
        from openbb_cftc.utils import dtcc, store

        self.model = swap_trades
        self.dtcc = dtcc
        self.today = datetime.now(timezone.utc).date()
        self.latest = self.today - timedelta(days=1)
        self.previous = self.latest - timedelta(days=1)
        self.reports = {}
        self.downloads = []
        self.curves = {}

        async def available(asset):
            self.assertEqual(asset, "rates")
            return sorted(self.reports)

        async def source(asset, day, use_cache=True):
            self.assertEqual(asset, "rates")
            self.downloads.append(day)
            payload = self.reports[day]
            if isinstance(payload, Exception):
                raise payload
            return payload

        def put_curve(key, day, payload):
            self.curves[key] = payload

        for target, name, replacement in (
            (dtcc, "get_available_dates", available),
            (dtcc, "get_slice", source),
            (store, "get_curve", self.curves.get),
            (store, "put_curve", put_curve),
        ):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def trade(self, day, identifier, valid=True):
        return {
            "Dissemination Identifier": identifier,
            "Asset Class": "IR",
            "Action type": "NEWT",
            "Event type": "TRAD",
            "UPI FISN": "NA/Swap OIS USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "Notional currency-Leg 1": "USD",
            "Notional amount-Leg 1": "100000000" if valid else "",
            "Fixed rate-Leg 1": "0.04",
            "Effective Date": day.isoformat(),
            "Expiration Date": (day + timedelta(days=365)).isoformat(),
            "Fixed rate day count convention-leg 1": "A004",
            "Cleared": "Y",
        }

    def fetch(self, **params):
        query = self.model.CftcSwapTradesFetcher.transform_query(params)
        rows = asyncio.run(self.model.CftcSwapTradesFetcher.aextract_data(query, None))
        return self.model.CftcSwapTradesFetcher.transform_data(query, rows)

    def test_default_unpriceable_latest_report_uses_previous_priceable_day(self):
        self.reports = {
            self.latest.isoformat(): [self.trade(self.latest, "100", valid=False)],
            self.previous.isoformat(): [self.trade(self.previous, "200")],
        }
        rows = self.fetch(limit=100)
        self.assertEqual([row.trade_key for row in rows], ["IR:200"])
        self.assertEqual(self.downloads, [self.latest.isoformat(), self.previous.isoformat()])

    def test_limit_one_skips_an_unpriceable_eligible_first_row(self):
        from openbb_core.provider.utils.errors import EmptyDataError

        self.reports[self.previous.isoformat()] = [
            self.trade(self.previous, "100", valid=False),
            self.trade(self.previous, "200"),
        ]
        try:
            rows = self.fetch(start_date=self.previous, end_date=self.previous, limit=1)
        except EmptyDataError:
            self.fail("limit=1 hid the later priceable transaction")
        self.assertEqual([row.trade_key for row in rows], ["IR:200"])

    def test_limit_stops_per_row_pricing_after_accepted_result(self):
        self.reports[self.previous.isoformat()] = [
            self.trade(self.previous, str(200 + index)) for index in range(1000)
        ]
        with mock.patch.object(self.model, "_priceable", wraps=self.model._priceable) as gate:
            rows = self.fetch(start_date=self.previous, end_date=self.previous, limit=1)
        self.assertEqual([row.trade_key for row in rows], ["IR:200"])
        self.assertEqual(gate.call_count, 1)

    def test_explicit_unpriceable_date_stays_empty_without_fallback(self):
        from openbb_core.provider.utils.errors import EmptyDataError

        self.reports = {
            self.latest.isoformat(): [self.trade(self.latest, "100", valid=False)],
            self.previous.isoformat(): [self.trade(self.previous, "200")],
        }
        with self.assertRaises(EmptyDataError):
            self.fetch(start_date=self.latest, end_date=self.latest, limit=1)
        self.assertEqual(self.downloads, [self.latest.isoformat()])

    def test_default_exhaustion_does_not_download_beyond_existing_lookback(self):
        from openbb_core.provider.utils.errors import EmptyDataError

        for offset in range(11):
            day = self.latest - timedelta(days=offset)
            self.reports[day.isoformat()] = [self.trade(day, str(offset), valid=offset == 10)]
        with self.assertRaises(EmptyDataError):
            self.fetch(limit=1)
        self.assertEqual(len(self.downloads), 10)
        self.assertNotIn(min(self.reports), self.downloads)

    def test_source_transport_error_is_not_empty_data_or_date_fallback(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        failure = OpenBBError("synthetic upstream transport failure")
        self.reports = {
            self.latest.isoformat(): failure,
            self.previous.isoformat(): [self.trade(self.previous, "200")],
        }
        with self.assertRaisesRegex(OpenBBError, "synthetic upstream transport failure"):
            self.fetch(limit=1)
        self.assertEqual(self.downloads, [self.latest.isoformat()])

    def test_full_global_limit_ignores_a_later_malformed_unselected_row(self):
        later = self.trade(self.latest, "300")
        later["Option Premium Amount"] = "bad"
        self.reports = {
            self.previous.isoformat(): [self.trade(self.previous, "200")],
            self.latest.isoformat(): [later],
        }
        with mock.patch.object(self.model, "_priceable", wraps=self.model._priceable) as gate:
            try:
                rows = self.fetch(start_date=self.previous, end_date=self.latest, limit=1)
            except Exception as exc:
                self.fail(f"An unselected later row failed the bounded query: {type(exc).__name__}")
        self.assertEqual([row.trade_key for row in rows], ["IR:200"])
        self.assertEqual(gate.call_count, 1)

    def test_second_date_prices_only_the_remaining_global_count(self):
        self.reports = {
            self.previous.isoformat(): [self.trade(self.previous, "200")],
            self.latest.isoformat(): [self.trade(self.latest, str(300 + i)) for i in range(3)],
        }
        with mock.patch.object(self.model, "_priceable", wraps=self.model._priceable) as gate:
            rows = self.fetch(start_date=self.previous, end_date=self.latest, limit=2)
        self.assertEqual([row.trade_key for row in rows], ["IR:200", "IR:300"])
        self.assertEqual(gate.call_count, 2)

    def test_unlimited_explicit_window_keeps_all_days_in_order(self):
        self.reports = {
            self.previous.isoformat(): [self.trade(self.previous, "200")],
            self.latest.isoformat(): [self.trade(self.latest, "300"), self.trade(self.latest, "301")],
        }
        rows = self.fetch(start_date=self.previous, end_date=self.latest)
        self.assertEqual([row.trade_key for row in rows], ["IR:200", "IR:300", "IR:301"])

    def test_forex_acceptance_skips_invalid_rows_and_reuses_its_memo(self):
        records = [{"Asset Class": "FX", "Dissemination Identifier": str(i)} for i in [100, 200, 300]]
        calls = []
        memos = []

        def value(record, *args, memo, **kwargs):
            calls.append(record["Dissemination Identifier"])
            memos.append(memo)
            memo["seen"] = memo.get("seen", 0) + 1
            return None if record["Dissemination Identifier"] == "100" else {"price": 1}

        query = self.model.CftcSwapTradesQueryParams(asset_class="forex", limit=1)
        with mock.patch.object(self.dtcc, "get_slice", mock.AsyncMock(return_value=[])), mock.patch("openbb_cftc.utils.fx_valuation.value_fx_trade", side_effect=value):
            rows = asyncio.run(self.model._keep_priceable_forex(records, records, self.previous.isoformat(), query))
        self.assertEqual([row["Dissemination Identifier"] for row in rows], ["200"])
        self.assertEqual(calls, ["100", "200"])
        self.assertIs(memos[0], memos[1])
        self.assertEqual(memos[0]["seen"], 2)

    def test_forex_ticker_preserves_cheap_filter_limit_without_pricing(self):
        records = [{"Asset Class": "FX", "Dissemination Identifier": str(i), "Unique Product Identifier": "TESTUPI"} for i in [100, 200]]
        with mock.patch("openbb_cftc.utils.search.search_trades", mock.AsyncMock(return_value=records)), mock.patch.object(self.model, "_keep_priceable", side_effect=AssertionError("Ticker forex did not previously require pricing")):
            rows = self.fetch(asset_class="forex", ticker="TESTUPI", start_date=self.previous, end_date=self.previous, limit=1)
        self.assertEqual([row.trade_key for row in rows], ["FX:100"])

    def test_rates_ticker_limit_counts_priceable_rows(self):
        records = [self.trade(self.previous, "100", valid=False), self.trade(self.previous, "200"), self.trade(self.previous, "300")]
        for record in records:
            record["Unique Product Identifier"] = "TESTUPI"
        with mock.patch("openbb_cftc.utils.search.search_trades", mock.AsyncMock(return_value=records)), mock.patch.object(self.dtcc, "get_rates_slice_for", mock.AsyncMock(return_value=(records, self.previous.isoformat()))), mock.patch.object(self.model, "_priceable", wraps=self.model._priceable) as gate:
            rows = self.fetch(ticker="TESTUPI", start_date=self.previous, end_date=self.previous, limit=1)
        self.assertEqual([row.trade_key for row in rows], ["IR:200"])
        self.assertEqual(gate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
