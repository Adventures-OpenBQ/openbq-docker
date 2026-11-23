# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""A failed quote batch must not be reported as an empty exchange response."""
import unittest
from unittest.mock import AsyncMock, patch


class DeribitTickerFailures(unittest.IsolatedAsyncioTestCase):
    async def test_all_failed_quotes_preserve_the_first_source_error(self):
        from openbb_deribit.utils.helpers import get_tickers

        error = TimeoutError("Synthetic public ticker timeout")
        with patch("openbb_deribit.utils.client.gather", AsyncMock(return_value=[error, ValueError("Second failure")])):
            with self.assertRaises(TimeoutError) as raised:
                await get_tickers(["BTC-PERPETUAL", "ETH-PERPETUAL"])
        self.assertIs(raised.exception, error)

    async def test_mixed_batch_keeps_successful_quote_and_flattened_statistics(self):
        from openbb_deribit.utils.helpers import get_tickers

        quote = {"instrument_name": "BTC-PERPETUAL", "last_price": 50, "stats": {"volume": 12}}
        with patch("openbb_deribit.utils.client.gather", AsyncMock(return_value=[TimeoutError(), quote])):
            result = await get_tickers(["ETH-PERPETUAL", "BTC-PERPETUAL"])
        self.assertEqual(result, [{"instrument_name": "BTC-PERPETUAL", "last_price": 50, "volume": 12}])
        self.assertIn("stats", quote)

    async def test_genuinely_empty_results_stay_empty(self):
        from openbb_deribit.utils.helpers import get_tickers

        for results in [[], [None, {}]]:
            with self.subTest(results=results), patch("openbb_deribit.utils.client.gather", AsyncMock(return_value=results)):
                self.assertEqual(await get_tickers([]), [])

    async def test_actual_futures_info_fetcher_preserves_the_transport_failure(self):
        from openbb_deribit.models.futures_info import DeribitFuturesInfoFetcher as Fetcher

        error = TimeoutError("Synthetic public ticker timeout")
        with patch("openbb_deribit.utils.helpers.get_perpetual_symbols", AsyncMock(return_value={"BTC": "BTC-PERPETUAL"})), patch("openbb_deribit.utils.client.gather", AsyncMock(return_value=[error])):
            try:
                await Fetcher.aextract_data(Fetcher.transform_query({"symbol": "BTC"}), None)
            except Exception as actual:
                self.assertIs(actual, error)
            else:
                self.fail("A failed transport returned a successful empty result")

    async def curve(self, error, history, hours="24"):
        from openbb_deribit.models.futures_curve import DeribitFuturesCurveFetcher as Fetcher

        query = Fetcher.transform_query({"symbol": "BTC", "hours_ago": hours})
        with patch("openbb_deribit.utils.helpers.get_futures_curve_symbols", AsyncMock(return_value=["BTC-31DEC26"])), patch("openbb_deribit.utils.helpers.get_tickers", AsyncMock(side_effect=error)), patch("openbb_deribit.utils.helpers.get_futures_curve_by_hours_ago", AsyncMock(return_value=history)):
            data = await Fetcher.aextract_data(query, None)
        return Fetcher.transform_data(query, data)

    async def test_curve_keeps_valid_history_when_current_quotes_fail(self):
        error = TimeoutError("Synthetic current-quote timeout")
        history = [{"instrument_name": "BTC-31DEC26", "last_price": 100, "hours_ago": 24}]
        try:
            result = await self.curve(error, history)
        except Exception as exc:
            self.fail(f"Current failure hid available historical data: {type(exc).__name__}")
        self.assertEqual([(row.price, row.hours_ago) for row in result], [(100, 24)])

    async def test_curve_preserves_current_error_if_history_is_also_empty(self):
        error = TimeoutError("Synthetic current-quote timeout")
        with self.assertRaises(TimeoutError) as raised:
            await self.curve(error, [])
        self.assertIs(raised.exception, error)

    async def test_current_only_curve_preserves_the_source_error(self):
        error = TimeoutError("Synthetic current-quote timeout")
        with self.assertRaises(TimeoutError) as raised:
            await self.curve(error, [], hours=None)
        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
