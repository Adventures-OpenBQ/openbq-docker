# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Cboe's origin header must survive both cached and direct request paths."""
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from pandas import DataFrame
from openbb_core.app.model.abstract.error import OpenBBError

ROOT=Path(__file__).parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
helpers=load('cboe_feed_helper_overlay','openbb_cboe/utils/helpers.py')

class FeedHeaders(IsolatedAsyncioTestCase):
    async def test_uncached_adds_referer_and_preserves_options_and_input_headers(self):
        headers={'X-Request-ID':'test'};remote=AsyncMock(return_value={'data':[]})
        with patch.object(helpers,'amake_request',remote):
            await helpers.get_cboe_data('https://cdn.cboe.com/options.json',use_cache=False,headers=headers,timeout=23)
        options=remote.call_args.kwargs
        self.assertEqual(options['headers'],{'X-Request-ID':'test','Referer':'https://www.cboe.com/'})
        self.assertEqual(options['timeout'],23);self.assertEqual(headers,{'X-Request-ID':'test'})

    async def test_cached_respects_explicit_case_insensitive_referer_and_timeout(self):
        headers={'referer':'https://www.cboe.com/explicit','Accept':'application/json'}
        response=SimpleNamespace(status=200,headers={'Content-Type':'application/json'},json=AsyncMock(return_value={'data':[]}))
        session=SimpleNamespace(get=AsyncMock(return_value=response))
        @asynccontextmanager
        async def backend():yield object()
        @asynccontextmanager
        async def cached(**kwargs):yield session
        with patch.object(helpers,'cache_backend',backend),patch('aiohttp_client_cache.session.CachedSession',cached):
            await helpers.get_cboe_data('https://cdn.cboe.com/options.json',headers=headers,timeout=23)
        self.assertEqual(session.get.call_args.kwargs['headers'],headers)
        self.assertEqual(session.get.call_args.kwargs['timeout'],23)

    async def test_error_status_is_rejected_before_decoding_or_consumer_get(self):
        response=SimpleNamespace(status=403,headers={'Content-Type':'text/html'},raise_for_status=Mock(side_effect=RuntimeError('HTTP403')),text=AsyncMock(return_value='<html>Denied</html>'))
        with self.assertRaisesRegex(RuntimeError,'HTTP403'):await helpers.response_callback(response,None)
        response.text.assert_not_called()

    async def test_futures_refuses_invalid_json_shape_and_forwards_request_options(self):
        remote=AsyncMock(return_value='<html>Wrong response</html>')
        with patch.object(helpers,'get_cboe_data',remote),self.assertRaisesRegex(OpenBBError,'JSON'):
            await helpers.list_futures(headers={'X-Request-ID':'test'})
        self.assertEqual(remote.call_args.kwargs['headers'],{'X-Request-ID':'test'})

    async def test_historical_batch_has_origin_header_and_preserves_request_options(self):
        model=load('cboe_historical_header_overlay','openbb_cboe/models/equity_historical.py')
        async def remote(urls,**kwargs):
            self.assertEqual(kwargs['headers'],{'Referer':'https://www.cboe.com/'});self.assertEqual(kwargs['timeout'],23);return []
        directory=DataFrame(columns=['index_symbol','name','source'])
        with patch('openbb_core.provider.utils.helpers.amake_requests',remote),patch('openbb_cboe.utils.helpers.get_index_directory',AsyncMock(return_value=directory)):
            await model.CboeEquityHistoricalFetcher.aextract_data(model.CboeEquityHistoricalQueryParams(symbol='SPY'),None,timeout=23)

    async def test_snapshots_direct_request_has_origin_header(self):
        model=load('cboe_snapshot_header_overlay','openbb_cboe/models/index_snapshots.py')
        async def remote(url,**kwargs):
            self.assertEqual(kwargs['headers'],{'Referer':'https://www.cboe.com/'});return {'data':[]}
        with patch('openbb_core.provider.utils.helpers.amake_request',remote):
            await model.CboeIndexSnapshotsFetcher.aextract_data(model.CboeIndexSnapshotsQueryParams(region='us'),None)

    async def test_options_chain_direct_request_preserves_headers_and_timeout(self):
        model=load('cboe_chain_header_overlay','openbb_cboe/models/options_chains.py')
        directory=DataFrame({'index_symbol':['VIX']})
        companies=DataFrame(index=['AAPL'])
        remote=AsyncMock(return_value={'data':{'options':[]}})
        with patch('openbb_core.provider.utils.helpers.amake_request',remote),patch('openbb_cboe.utils.helpers.get_index_directory',AsyncMock(return_value=directory)),patch('openbb_cboe.utils.helpers.get_company_directory',AsyncMock(return_value=companies)):
            await model.CboeOptionsChainsFetcher.aextract_data(model.CboeOptionsChainsQueryParams(symbol='AAPL'),None,headers={'X-Request-ID':'test'},timeout=23)
        self.assertEqual(remote.call_args.kwargs['headers'],{'X-Request-ID':'test','Referer':'https://www.cboe.com/'})
        self.assertEqual(remote.call_args.kwargs['timeout'],23)
