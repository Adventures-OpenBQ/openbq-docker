# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Distinguish Nasdaq vendor failures from legitimate empty datasets."""
import unittest
from unittest.mock import AsyncMock, patch


class NasdaqVendorErrors(unittest.IsolatedAsyncioTestCase):
    async def request(self, response):
        from openbb_nasdaq.utils.helpers import get_nasdaq_data
        with patch('openbb_nasdaq.utils.helpers._live_request', new=AsyncMock(return_value=response)):
            return await get_nasdaq_data('quote/NVDA/option-chain?assetclass=stocks', use_cache=False)

    async def test_vendor_failure_in_success_envelope_is_an_error(self):
        from openbb_core.app.model.abstract.error import OpenBBError
        for data in [None, {'table': {'rows': [{'strike': 100}]}}]:
            with self.subTest(data=data), self.assertRaisesRegex(OpenBBError, 'Error while calling vendor'):
                await self.request({'status': {'rCode': 200, 'bCodeMessage': [{'code': 3004, 'errorMessage': 'Error while calling vendor'}]}, 'data': data})

    async def test_string_vendor_error_code_is_also_an_error(self):
        from openbb_core.app.model.abstract.error import OpenBBError
        with self.assertRaises(OpenBBError):
            await self.request({'status': {'rCode': 200, 'bCodeMessage': [{'code': '3004', 'errorMessage': 'Error while calling vendor'}]}, 'data': None})

    async def test_empty_success_without_vendor_error_stays_empty(self):
        self.assertIsNone(await self.request({'status': {'rCode': 200, 'bCodeMessage': None}, 'data': None}))

    async def test_successful_data_is_unchanged(self):
        data = {'table': {'rows': [{'strike': 100}]}}
        self.assertEqual(await self.request({'status': {'rCode': 200}, 'data': data}), data)
