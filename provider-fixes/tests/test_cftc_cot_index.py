# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The COT positioning index asks CFTC for the weeks it scores, not each market's history from 1995."""
import asyncio
import re
import unittest
from datetime import date, timedelta
from unittest import mock

TODAY = date.today()
# The newest report a caller can see: the Tuesday at least a week back.
LATEST = TODAY - timedelta(days=(TODAY.weekday() - 1) % 7 + 7)


def tuesdays(weeks, latest=LATEST):
    return [latest - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]


def report(day):
    n = day.toordinal()
    return {
        "report_date_as_yyyy_mm_dd": f"{day}T00:00:00.000",
        "open_interest_all": str(100000 + n % 977),
        "noncomm_positions_long_all": str(n * 7919 % 50000),
        "noncomm_positions_short_all": str(n * 104729 % 50000),
        "nonrept_positions_long_all": str(n * 1299709 % 9000),
        "nonrept_positions_short_all": str(n * 15485863 % 9000),
        "comm_positions_long_all": str(n * 32452843 % 70000),
        "comm_positions_short_all": str(n * 49979687 % 70000),
    }


class CotIndexWindowTest(unittest.TestCase):
    def setUp(self):
        from openbb_cftc.utils import store
        from openbb_core.provider.utils import helpers

        self.days = tuesdays(1600)  # reports back to the mid-1990s
        self.urls, self.cache = [], {}

        async def upstream(url, **_):
            self.urls.append(url)
            start, end = re.search(r"between '([\d-]+)' AND '([\d-]+)'", url).groups()
            return [report(d) for d in self.days if start <= d.isoformat() <= end]

        for target, name, fake in (
            (helpers, "amake_request", upstream),
            (store, "get_response", self.cache.get),
            (store, "put_response", self.cache.__setitem__),
        ):
            patcher = mock.patch.object(target, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def index(self, lookback_weeks):
        from openbb_cftc.models.cot_index import CftcCotIndexFetcher

        query = CftcCotIndexFetcher.transform_query({"asset_class": "currencies", "lookback_weeks": lookback_weeks})
        return asyncio.run(CftcCotIndexFetcher.aextract_data(query, None))

    def full_history_scores(self, lookback_weeks):
        from openbb_cftc.models.cot_index import score_market
        from openbb_cftc.utils.cot_markets import markets_for

        rows = [report(d) for d in self.days]
        return [score_market(market, rows, lookback_weeks) for market in markets_for("currencies")]

    def starts(self):
        return [re.search(r"between '([\d-]+)'", url).group(1) for url in self.urls]

    def test_asks_only_for_the_lookback_window(self):
        for lookback_weeks in (52, 260):
            with self.subTest(lookback_weeks=lookback_weeks):
                self.urls.clear()
                self.cache.clear()
                self.assertEqual(self.index(lookback_weeks), self.full_history_scores(lookback_weeks))
                self.assertEqual(len(self.urls), 6)
                earliest = (TODAY - timedelta(weeks=lookback_weeks + 5)).isoformat()
                self.assertEqual(set(self.starts()), {earliest})

    def test_window_is_never_served_to_a_full_history_caller(self):
        from openbb_cftc.models.cot import CftcCotFetcher, CftcCotQueryParams
        from openbb_cftc.utils.cot_markets import markets_for

        self.index(52)
        code = markets_for("currencies")[0]["code"]
        query = CftcCotQueryParams(code=code, report_type="legacy", measure="positions", futures_only=True)
        rows = asyncio.run(CftcCotFetcher.aextract_data(query, None))
        self.assertEqual(len(rows), len(self.days))
        self.assertEqual(self.starts()[-1], "1995-01-01")
        # And the index does not score a cached full history's window from a different lookback.
        self.assertEqual(self.index(52), self.full_history_scores(52))
        self.assertEqual(len(self.cache), 7)

    def test_too_few_reports_in_the_window_scores_the_full_history(self):
        cases = {
            "publication gap": tuesdays(1600, LATEST - timedelta(weeks=10)),
            "market younger than the lookback": tuesdays(30),
            "market that stopped reporting": tuesdays(400, LATEST - timedelta(weeks=80)),
        }
        for name, self.days in cases.items():
            with self.subTest(name):
                self.urls.clear()
                self.cache.clear()
                self.assertEqual(self.index(52), self.full_history_scores(52))
                self.assertIn("1995-01-01", self.starts())

    def test_lookback_outside_the_window_range_keeps_upstream_request(self):
        for lookback_weeks in (0, -3, 1500):
            with self.subTest(lookback_weeks=lookback_weeks):
                self.urls.clear()
                self.cache.clear()
                self.assertEqual(self.index(lookback_weeks), self.full_history_scores(lookback_weeks))
                self.assertEqual(self.starts(), ["1995-01-01"] * 6)


if __name__ == "__main__":
    unittest.main()
