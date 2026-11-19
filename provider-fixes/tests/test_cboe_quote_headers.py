# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Delayed quote requests need Cboe's same-site referer on both feeds."""
import importlib.util
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from pandas import DataFrame
import openbb_cboe.models.equity_quote as installed

source = Path(__file__).parents[1] / "openbb_cboe/models/equity_quote.py"
if source.exists():
    spec = importlib.util.spec_from_file_location("cboe_quote_overlay", source)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
else:
    model = installed


class CboeQuoteHeadersTests(IsolatedAsyncioTestCase):
    async def check_request(self, headers, expected):
        calls = []
        async def remote(urls, **kwargs):
            calls.append((urls, kwargs))
            self.assertEqual(kwargs.get("headers"), expected)
            self.assertEqual(kwargs.get("timeout"), 23)
            if "historical_data" in urls[0]:
                return [{"data": {"symbol": "SPY", "iv30": 19.5}}]
            return [{"data": {"symbol": "SPY", "current_price": 680.5}}]

        companies = DataFrame([{"symbol": "SPY", "name": "SPDR"}]).set_index("symbol")
        indexes = DataFrame(columns=["index_symbol", "source", "name"])
        query = model.CboeEquityQuoteQueryParams(symbol="SPY")
        with patch("openbb_core.provider.utils.helpers.amake_requests", remote), patch(
            "openbb_cboe.utils.helpers.get_company_directory", AsyncMock(return_value=companies)
        ), patch("openbb_cboe.utils.helpers.get_index_directory", AsyncMock(return_value=indexes)):
            result = await model.CboeEquityQuoteFetcher.aextract_data(
                query, None, headers=headers, timeout=23
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.loc["SPY", "current_price"], 680.5)
        self.assertEqual(result.loc["SPY", "iv30"], 19.5)

    async def test_default_referer_reaches_quote_and_history_without_mutating_headers(self):
        headers = {"X-Request-ID": "caller"}
        await self.check_request(headers, {"Referer": "https://www.cboe.com/", "X-Request-ID": "caller"})
        self.assertEqual(headers, {"X-Request-ID": "caller"})

    async def test_explicit_case_insensitive_referer_and_kwargs_are_preserved(self):
        headers = {"referer": "https://www.cboe.com/delayed_quotes/spy/quote_table", "Accept": "application/json"}
        await self.check_request(headers, dict(headers))
