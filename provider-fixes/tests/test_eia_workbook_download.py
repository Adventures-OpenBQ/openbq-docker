"""Keyless HTTP contract regression tests for the public EIA workbook loader."""
from io import BytesIO
import unittest
from unittest.mock import patch
import pandas as pd
from openbb_us_eia.utils.helpers import download_excel_file

class WorkbookDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        download_excel_file.cache_clear()

    async def asyncTearDown(self):
        download_excel_file.cache_clear()

    async def test_workbook_request_accepts_excel_instead_of_json(self):
        stream = BytesIO()
        pd.DataFrame({'value':[92.94]}).to_excel(stream,index=False,engine='openpyxl')
        class Response:
            status=200
            async def read(self): return stream.getvalue()
        async def request(url, response_callback, **kwargs):
            self.assertEqual(kwargs.get('headers',{}).get('Accept'), '*/*')
            return await response_callback(Response(),None)
        with patch('openbb_core.provider.utils.helpers.amake_request',request):
            result=await download_excel_file('https://www.eia.gov/test-workbook.xlsx',False)
        self.assertEqual(pd.read_excel(result).iloc[0,0],92.94)

    async def test_http_error_is_reported_before_excel_parsing(self):
        class Response:
            status=406
            async def read(self):
                raise AssertionError('An unsuccessful response must not be parsed')
        async def request(url,response_callback,**kwargs):
            return await response_callback(Response(),None)
        with patch('openbb_core.provider.utils.helpers.amake_request',request):
            with self.assertRaisesRegex(Exception,'HTTP 406'):
                await download_excel_file('https://www.eia.gov/test-denied.xls',False)

if __name__=='__main__': unittest.main()
