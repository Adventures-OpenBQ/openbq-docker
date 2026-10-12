# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""G3b: FRED TIPS, Fama-French Australia, Cboe settlements, Nasdaq splits, FFIEC peer group, KC Fed Ag."""
import asyncio
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

FIXTURES = Path(__file__).parent / "fixtures"


class FredTipsYieldsTest(unittest.TestCase):
    def test_five_year_is_not_a_maturity_choice(self):
        # FRED publishes no live 5-year TIPS (every 5-year series in release 72 is discontinued).
        from pydantic import ValidationError
        from openbb_fred.models.tips_yields import FredTipsYieldsFetcher, FredTipsYieldsQueryParams

        self.assertEqual(
            FredTipsYieldsQueryParams.model_fields["maturity"].json_schema_extra["choices"],
            ["10", "20", "30"],
        )
        with self.assertRaises(ValidationError):
            FredTipsYieldsFetcher.transform_query({"maturity": "5"})


class FamaFrenchCountryFilesTest(unittest.TestCase):
    # The members of F-F_International_Countries.zip (and _Wout_Div.zip), 2026-10-09.
    ZIP_MEMBERS = {
        "Austria.Dat", "Austrlia.Dat", "Belgium.Dat", "Canada.Dat", "Denmark.Dat",
        "Finland.Dat", "France.Dat", "Germany.Dat", "HongKong.Dat", "Ireland.Dat",
        "Italy.Dat", "Japan.Dat", "Malaysia.Dat", "Nethrlnd.Dat", "NewZland.Dat",
        "Norway.Dat", "Singapor.Dat", "Spain.Dat", "Sweden.Dat", "Swtzrlnd.Dat", "UK.Dat",
    }

    def test_every_country_maps_to_a_zip_member(self):
        from openbb_famafrench.utils.constants import COUNTRY_PORTFOLIO_FILES

        missing = {k: v for k, v in COUNTRY_PORTFOLIO_FILES.items() if v not in self.ZIP_MEMBERS}
        self.assertEqual(missing, {})


class CboeSettlementPriceTest(unittest.TestCase):
    def test_non_numeric_price_becomes_null(self):
        from openbb_cboe.models.futures_settlements import CboeFuturesSettlementsFetcher

        csv = (
            "Product,Symbol,Expiration Date,Price\n"
            "IBYO,IBYO/H7 P16800,2027-03-01,0.7389\n"
            "IBYO,IBYO/Z6 P17000,2026-12-01,CAB\n"
        )
        query = CboeFuturesSettlementsFetcher.transform_query({"options": True})
        with mock.patch(
            "openbb_cboe.utils.helpers.get_cboe_data", mock.AsyncMock(return_value=csv)
        ):
            rows = asyncio.run(CboeFuturesSettlementsFetcher.aextract_data(query, None))
        result = CboeFuturesSettlementsFetcher.transform_data(query, rows)
        self.assertEqual([r.price for r in result], [0.7389, None])


class NasdaqCalendarSplitsTest(unittest.TestCase):
    def test_unparseable_ratio_keeps_the_row(self):
        from openbb_nasdaq.models.calendar_splits import NasdaqCalendarSplitsFetcher

        query = NasdaqCalendarSplitsFetcher.transform_query(
            {"start_date": date(2026, 7, 1), "end_date": date(2026, 9, 30)}
        )
        rows = [
            {"symbol": "AAA", "name": "A", "ratio": "1 : 10", "executionDate": "7/1/2026"},
            {"symbol": "BBB", "name": "B", "ratio": "1-for-10", "executionDate": "7/2/2026"},
            {"symbol": "SNFCA", "name": "C", "ratio": "5%", "executionDate": "7/10/2026"},
        ]
        result = NasdaqCalendarSplitsFetcher.transform_data(query, rows)
        self.assertEqual(
            [(r.symbol, r.numerator, r.denominator, r.ratio_display) for r in result],
            [("AAA", 1.0, 10.0, "1 : 10"), ("BBB", None, None, "1-for-10"), ("SNFCA", None, None, "5%")],
        )


class FfiecPeerGroupAmountsTest(unittest.TestCase):
    def test_fractional_thousands_round_to_dollars(self):
        from openbb_federal_reserve.models.list_of_banks_peer_group import (
            FederalReserveListOfBanksPeerGroupFetcher,
        )

        rows = [{"rssd_id": "1", "average_assets": 1234.5678, "net_income": -0.5}]
        result = FederalReserveListOfBanksPeerGroupFetcher.transform_data(None, rows)
        self.assertEqual((result[0].average_assets, result[0].net_income), (1234568, -500))


class KansasCityAgTest(unittest.TestCase):
    INDEX = (
        b'<a href="/documents/7623/Q226-landvalues.xlsx">x</a>'
        b'<a href="/documents/7622/Q226-variableinterestrates.xlsx">x</a>'
        b'<a href="/documents/7889/CommercialBankCallReportDataTablesQ22026.xlsx">x</a>'
    )

    def _run(self, fetcher, params, document_id):
        from openbb_federal_reserve.utils.kansas_city_ag import _INDEX_URL

        workbook = (FIXTURES / f"{document_id}.xlsx").read_bytes()
        urls = []

        def fetch(url):
            urls.append(url)
            if url == _INDEX_URL:
                return self.INDEX
            resolved = f"https://www.kansascityfed.org/documents/{document_id}/"
            return workbook if url.startswith(resolved) else b""

        query = fetcher.transform_query(params)
        with mock.patch(
            "openbb_federal_reserve.utils.cache.cached", lambda key, ttl, producer: producer()
        ), mock.patch("openbb_federal_reserve.utils.kansas_city.fetch_kansas_city", fetch):
            data = fetcher.extract_data(query, None)
        self.assertEqual(urls[0], _INDEX_URL)
        return fetcher.transform_data(query, data)

    def _cached_hit_skips_the_index(self, fetcher, params):
        fetch = mock.Mock()
        query = fetcher.transform_query(params)
        with mock.patch(
            "openbb_federal_reserve.utils.cache.cached", lambda key, ttl, producer: b"cached"
        ), mock.patch("openbb_federal_reserve.utils.kansas_city.fetch_kansas_city", fetch):
            fetcher.extract_data(query, None)
        fetch.assert_not_called()

    def test_credit_survey(self):
        from openbb_federal_reserve.models.regional.kansas_city_ag_credit_survey import (
            FederalReserveKansasCityAgCreditSurveyFetcher as F,
        )

        rows = self._run(F, {"table": "land_values"}, 7623)
        self.assertEqual(rows[-1].date, date(2026, 6, 30))
        self._cached_hit_skips_the_index(F, {"table": "land_values"})

    def test_interest_rates(self):
        from openbb_federal_reserve.models.regional.kansas_city_ag_rates import (
            FederalReserveKansasCityAgRatesFetcher as F,
        )

        rows = self._run(F, {"rate_type": "variable", "loan_type": "operating"}, 7622)
        self.assertEqual(rows[-1].model_dump()["Kansas"], 7.55)
        self._cached_hit_skips_the_index(F, {"rate_type": "variable"})

    def test_finance_databook(self):
        from openbb_federal_reserve.models.regional.kansas_city_ag_finance import (
            FederalReserveKansasCityAgFinanceFetcher as F,
        )

        rows = self._run(F, {"table": "ag_bank_performance"}, 7889)
        self.assertEqual(rows[-1].date, date(2026, 6, 30))
        self._cached_hit_skips_the_index(F, {"table": "ag_bank_performance"})


if __name__ == "__main__":
    unittest.main()
