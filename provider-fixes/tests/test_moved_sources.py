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


if __name__ == "__main__":
    unittest.main()
