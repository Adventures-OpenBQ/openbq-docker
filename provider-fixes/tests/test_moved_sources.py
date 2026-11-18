# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Sources that moved or changed shape: Atlanta Fed files, Minneapolis CSV header,
Cboe digit-root contracts, and the Congress bulk loader's lock across event loops."""
import asyncio
import importlib
import threading
import unittest

REGIONAL = "openbb_federal_reserve.models.regional"


class AtlantaMovedFilesTest(unittest.TestCase):
    def test_every_atlanta_url_is_under_research_and_data(self):
        for name in ("bie", "gdpnow", "market_probability", "sbu", "sticky_cpi",
                     "taylor_rule", "wage_growth"):
            with self.subTest(model=name):
                url = importlib.import_module(f"{REGIONAL}.atlanta_{name}").URL
                self.assertIn("/FRBA/Documents/research-and-data/", url)


class MinneapolisPeriodColumnTest(unittest.TestCase):
    PERFORMANCE = "month,Investment,Headcount,Hiring,Inventories,Profits,Sales\nFeb 2022,28.18,-1.82,40.91,-2.8,-20,30\n"

    def test_prices_period_column_named_month_or_date(self):
        module = importlib.import_module(f"{REGIONAL}.minneapolis_business_conditions")
        fetcher = module.FederalReserveMinneapolisBusinessConditionsFetcher
        for header in ("month", "Date"):
            with self.subTest(header=header):
                prices = f"{header},Benefits,Input prices,Sales prices,Wages\nFeb 2022,30.56,72.22,56.36,56.88\nMar 2022 (F),1,2,3,4\n"
                rows = fetcher.transform_data(
                    fetcher.transform_query({}), [{"_prices": prices, "_performance": self.PERFORMANCE}]
                )
                self.assertEqual([(str(r.date), r.wages, r.sales) for r in rows],
                                 [("2022-02-01", 56.88, 30.0), ("2022-03-01", 4.0, None)])
                self.assertEqual([r.is_flash for r in rows], [False, True])


class DallasSurveySheetNameTest(unittest.TestCase):
    def test_survey_sheet_named_index_or_sheet1(self):
        from io import BytesIO

        from openpyxl import Workbook

        cases = (("dallas_tmos", "FederalReserveDallasManufacturing", ["date", "Prod", "Fprod"]),
                 ("dallas_tssos", "FederalReserveDallasServiceSector", ["date ", "rev", "frev"]))
        for module_name, prefix, header in cases:
            module = importlib.import_module(f"{REGIONAL}.{module_name}")
            fetcher = getattr(module, prefix + "Fetcher")
            for sheet in ("Index", "Sheet1"):
                with self.subTest(model=module_name, sheet=sheet):
                    book, raw = Workbook(), BytesIO()
                    book.active.title = sheet
                    book.active.append(header)
                    book.active.append(["Jun-04", 38, 50])
                    book.save(raw)
                    # Upstream raised "Worksheet named 'Index' not found" for Sheet1.
                    rows = fetcher.transform_data(fetcher.transform_query({}), [{"_raw": raw.getvalue()}])
                    self.assertEqual([str(r.date) for r in rows], ["2004-06-01"])


class FinraSecuritiesWithoutRetiredLookupTest(unittest.TestCase):
    def test_new_symbols_are_listed_without_the_market_data_lookup(self):
        from unittest import mock

        from openbb_finra.utils import client, directory

        async def universe():
            return {"AAPL": {"tier": "NMS Tier 1"}, "ZZNEW": {"tier": "OTC"}}

        known = ["ST", "Apple Inc", "Common Shares", "0P000000GY", "0P000000GY", "XNAS", "19", "126",
                 "USA", "USA", "USD", "126.1.AAPL"]
        # FINRA retired the lookup service; upstream called it for ZZNEW and raised "not readable".
        with mock.patch.object(directory, "load_universe", universe), \
                mock.patch.object(directory, "read_asset", lambda: {"securities": {"AAPL": known}}), \
                mock.patch.object(client, "market_data_session", side_effect=AssertionError("lookup called")):
            rows = asyncio.run(directory.list_securities())
        self.assertEqual([(r["symbol"], r.get("security_type")) for r in rows],
                         [("AAPL", "ST"), ("ZZNEW", None)])


class CboeDigitRootContractsTest(unittest.TestCase):
    def test_contracts_with_a_digit_in_the_root_parse(self):
        from openbb_cboe.models.options_chains import CboeOptionsChainsFetcher as fetcher

        quote = {"bid": 1.0, "ask": 1.1, "bid_size": 1, "ask_size": 1, "iv": 0.2, "open_interest": 5,
                 "volume": 2, "delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.1, "rho": 0.0,
                 "theo": 1.05, "change": 0.0, "open": 1.0, "high": 1.0, "low": 1.0, "tick": "up",
                 "last_trade_price": 1.0, "last_trade_time": "2026-11-17T15:59:59",
                 "percent_change": 0.0, "prev_day_close": 1.0}
        symbols = ["SPY261120C00710000", "SPY261120P00710000", "B1SPY261120C00710000"]
        data = {"data": {"symbol": "SPY", "current_price": 700.0,
                         "options": [{**quote, "option": s} for s in symbols]}}
        result = fetcher.transform_data(fetcher.transform_query({"symbol": "SPY"}), data).result
        self.assertEqual(sorted(result.contract_symbol), sorted(symbols))
        self.assertEqual({str(e)[:10] for e in result.expiration}, {"2026-11-20"})
        self.assertEqual(set(result.strike), {710.0})
        self.assertEqual(set(result.underlying_symbol), {"SPY", "B1SPY"})

    def test_term_structure_skips_a_side_with_no_otm_strike(self):
        from openbb_cboe.models.options_chains import CboeOptionsChainsFetcher as fetcher
        from openbb_cboe.utils.options.create_term_structure import create_term_structure

        quote = {"bid": 1.0, "ask": 1.1, "bid_size": 1, "ask_size": 1, "iv": 0.2, "open_interest": 5,
                 "volume": 2, "delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.1, "rho": 0.0,
                 "theo": 1.05, "change": 0.0, "open": 1.0, "high": 1.0, "low": 1.0, "tick": "up",
                 "last_trade_price": 1.0, "last_trade_time": "2026-11-17T15:59:59",
                 "percent_change": 0.0, "prev_day_close": 1.0}
        # The second expiry lists one strike, above the price: no out-of-the-money put.
        symbols = ["SPY271119C00710000", "SPY271119P00690000",
                   "SPY271202C00825000", "SPY271202P00825000"]
        data = {"data": {"symbol": "SPY", "current_price": 700.0,
                         "options": [{**quote, "option": s} for s in symbols]}}
        chain = fetcher.transform_data(fetcher.transform_query({"symbol": "SPY"}), data).result
        # Upstream raised "unsupported operand type(s) for -: 'float' and 'NoneType'" here.
        rows = create_term_structure(chain, metric="price").results
        self.assertEqual(sorted((str(r.expiration)[:10], r.option_type, r.strike) for r in rows),
                         [("2027-11-19", "call", 710.0), ("2027-11-19", "put", 690.0),
                          ("2027-12-02", "call", 825.0)])


class CboeConstituentsWithoutAFileTest(unittest.TestCase):
    def test_an_index_with_no_file_is_a_clear_error_and_the_app_opens_on_one_that_has(self):
        import json
        from pathlib import Path
        from unittest import mock

        import openbb_cboe
        from aiohttp import ClientResponseError
        from openbb_cboe.models.index_constituents import CboeIndexConstituentsFetcher as fetcher
        from openbb_core.app.model.abstract.error import OpenBBError

        async def forbidden(url, **kwargs):
            raise ClientResponseError(mock.Mock(real_url=url), (), status=403, message="Forbidden")

        # Upstream let the 403 surface as "Unexpected Error -> ContentTypeError" (500).
        with mock.patch("openbb_core.provider.utils.helpers.amake_request", forbidden), \
                self.assertRaisesRegex(OpenBBError, "no constituents for BUKENGY"):
            asyncio.run(fetcher.aextract_data(fetcher.transform_query({"symbol": "BUKENGY"}), None))
        apps = (Path(openbb_cboe.__file__).parent / "assets" / "apps.json").read_text()
        self.assertNotIn("BUKENGY", apps)
        self.assertIn('"BUK100P"', json.dumps(json.loads(apps)))


class CongressLoadLockAcrossLoopsTest(unittest.TestCase):
    def test_a_second_event_loop_waits_for_nothing_and_does_not_raise(self):
        from openbb_government_us.congress.utils import bulk

        key = "TEST_LOAD_LOCK_ACROSS_LOOPS"
        holding, release, outcome = threading.Event(), threading.Event(), {}

        async def slow():
            holding.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return ["first"]

        async def contend():
            # A second waiter on this loop makes the lock take its loop (the first never waits).
            return await asyncio.gather(bulk._memoized(key, slow), bulk._memoized(key, slow))

        def first_loop():
            outcome["first"] = asyncio.run(contend())

        thread = threading.Thread(target=first_loop)
        thread.start()
        try:
            self.assertTrue(holding.wait(5))

            async def other():
                return ["second"]

            # Upstream raised "is bound to a different event loop" here.
            self.assertEqual(asyncio.run(bulk._memoized(key, other)), ["second"])
        finally:
            release.set()
            thread.join(5)
            bulk.BillsState().bulk.pop(key, None)
        self.assertEqual(len(outcome["first"]), 2)


class CongressMandatedReportsFallbackTest(unittest.TestCase):
    def test_reports_come_from_the_search_when_the_link_route_fails(self):
        from unittest import mock

        from openbb_government_us.congress.models.congress_mandated_reports import (
            CongressMandatedReportsFetcher as fetcher,
        )
        from openbb_government_us.congress.utils import bulk

        async def broken(url, **kwargs):
            # GovInfo answers 500 with this body; upstream read it as an empty list.
            return {"message": "No static resource cmr/tableofreports for request '/link/cmr/tableofreports'."}

        async def search(query, **kwargs):
            return {"resultSet": [{
                "line1": "Quarterly Report",
                "line2": "Congressionally Mandated Reports. Department of Veterans Affairs. 119th Congress. November 6, 2026.",
                "fieldMap": {"packageid": "CMR-VA1-00203071"}}]}

        with mock.patch("openbb_core.provider.utils.helpers.amake_request", broken), \
                mock.patch.object(bulk, "wssearch", search):
            rows = asyncio.run(fetcher.fetch_data({"limit": 3}))
        self.assertEqual([(r.package_id, r.submitting_agency, str(r.publication_date), r.is_on_time) for r in rows],
                         [("CMR-VA1-00203071", "Department of Veterans Affairs", "2026-11-06", None)])


class UsdaLivestockTradeLayoutTest(unittest.TestCase):
    def test_workbook_with_descriptor_columns_on_every_row(self):
        from io import BytesIO

        from openbb_government_us.usda.utils import ers_livestock_and_meat_international_trade_data as ers
        from openpyxl import Workbook

        book, raw = Workbook(), BytesIO()
        for row in (
            ["Commodity description", "Trade flow", "Unit description", "Geography code",
             "Geography description", 2024, 2025, "Jan-Sep-25"],
            ["Beef and veal", "Imports", "1,000 pounds", 6021, "Australia", 1.0, 2.0, 3.0],
            ["Beef and veal", "Imports", "1,000 pounds", 0, "World total", 9.0, 9.0, 9.0],
            ["Beef and veal", "Exports", "1,000 pounds", 1220, "Canada", 4.0, 5.0, 6.0],
        ):
            book.active.append(row)
        book.save(raw)
        entry = ers.SPECIES["beef_veal"]
        # Upstream looked for an "Import/export" header and found no products (204).
        self.assertEqual(ers.parse_products(raw.getvalue(), entry, "imports"), ["Beef and veal"])
        records = ers.parse_workbook(raw.getvalue(), entry, "imports", "Beef and veal")
        self.assertEqual({r["country"] for r in records}, {"Australia"})
        self.assertEqual(len(records), 3)


class AtlantaPublicationsDoiOnlyItemsTest(unittest.TestCase):
    def test_an_item_with_only_a_doi_resolves_through_its_landing_page(self):
        from openbb_federal_reserve.utils import fedinprint

        pages = {
            "https://fedinprint.org/item/fedawp/1/original": '<meta name="citation_doi" content="10.29338/wp2026-19">',
            "https://doi.org/10.29338/wp2026-19": (
                '<meta property="og:url" content="https://www.atlantafed.org/research-and-data/publications/wp/19">'
                '<a href="/-/media/Project/Atlanta/FRBA/Documents/wp/19.pdf">Full text</a>'
            ),
        }
        # Upstream found no file link on the item page and dropped every recent Atlanta item (204).
        self.assertEqual(
            fedinprint.resolve_file("https://fedinprint.org/item/fedawp/1/original", pages.__getitem__),
            "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/wp/19.pdf",
        )


class OecdPresentationTableAppStateTest(unittest.TestCase):
    def test_the_app_opens_the_table_without_an_end_date(self):
        from pathlib import Path

        import openbb_oecd

        # With end_date=2020-01-01 and the widget's row limit, OECD answered with no data (400).
        self.assertNotIn('"end_date"', (Path(openbb_oecd.__file__).parent / "apps.json").read_text())


if __name__ == "__main__":
    unittest.main()
