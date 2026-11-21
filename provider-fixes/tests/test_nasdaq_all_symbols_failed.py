# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""An upstream failure for every symbol must not be reported as empty data."""
import unittest
import warnings
from unittest.mock import AsyncMock, patch


class NasdaqAllSymbolsFailed(unittest.IsolatedAsyncioTestCase):
    async def test_quote_profile_and_fund_keep_the_original_upstream_failure(self):
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_nasdaq.models.equity_quote import NasdaqEquityQuoteFetcher
        from openbb_nasdaq.models.equity_info import NasdaqEquityInfoFetcher
        from openbb_nasdaq.models.etf_info import NasdaqEtfInfoFetcher
        for fetcher in [NasdaqEquityQuoteFetcher, NasdaqEquityInfoFetcher, NasdaqEtfInfoFetcher]:
            with self.subTest(fetcher=fetcher.__name__):
                query = fetcher.transform_query({'symbol':'AAPL'})
                failure = OpenBBError('Error while calling vendor')
                with warnings.catch_warnings(), patch('openbb_nasdaq.utils.helpers.get_nasdaq_data', new=AsyncMock(side_effect=failure)), patch('openbb_nasdaq.utils.helpers.resolve_asset_class', new=AsyncMock(return_value='etf')):
                    warnings.simplefilter('ignore')
                    with self.assertRaises(OpenBBError) as caught:
                        await fetcher.aextract_data(query, {})
                    self.assertIs(caught.exception, failure)

    async def test_a_working_symbol_survives_when_another_symbol_fails(self):
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_nasdaq.models.equity_quote import NasdaqEquityQuoteFetcher
        from openbb_nasdaq.models.equity_info import NasdaqEquityInfoFetcher
        from openbb_nasdaq.models.etf_info import NasdaqEtfInfoFetcher
        async def source(path, **kwargs):
            if '/AAPL/' in path: raise OpenBBError('Error while calling vendor')
            return {'companyName':'Microsoft Corporation', 'primaryData':{'lastSalePrice':'$350'}}
        for fetcher in [NasdaqEquityQuoteFetcher, NasdaqEquityInfoFetcher, NasdaqEtfInfoFetcher]:
            with self.subTest(fetcher=fetcher.__name__):
                query = fetcher.transform_query({'symbol':'AAPL,MSFT'})
                with warnings.catch_warnings(), patch('openbb_nasdaq.utils.helpers.get_nasdaq_data', new=source), patch('openbb_nasdaq.utils.helpers.resolve_asset_class', new=AsyncMock(return_value='etf')):
                    warnings.simplefilter('ignore')
                    result = await fetcher.aextract_data(query, {})
                self.assertEqual([row['symbol'] for row in result], ['MSFT'])
