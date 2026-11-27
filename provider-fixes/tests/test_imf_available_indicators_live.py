import asyncio
import unittest
import warnings
from unittest.mock import patch
from openbb_imf.models.available_indicators import ImfAvailableIndicatorsFetcher as F

class AvailableIndicators(unittest.TestCase):
    def test_comma_list_from_fastapi_is_normalized(self):
        self.check_flows(['CPI,PCPS'])
    def test_documented_semicolon_and_whitespace_are_normalized(self):
        self.check_flows([' CPI ; PCPS '])
    def test_existing_scalar_comma_and_canonical_list_are_preserved(self):
        self.check_flows('CPI,PCPS')
        self.check_flows(['CPI','PCPS'])
    def test_model_normalizes_single_repeated_and_empty_tokens(self):
        for value,expected in [('BOP',['BOP']),(['BOP'],['BOP']),([' CPI, ','',' ; PCPS; '],['CPI','PCPS']),('',[]),([' ; , '],[]),(None,None)]:
            with self.subTest(value=value):self.assertEqual(F.transform_query({'dataflows':value}).dataflows,expected)
    def check_flows(self,value):
        with patch('openbb_core.provider.utils.helpers.make_request',side_effect=AssertionError('No network permitted')):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                rows=asyncio.run(F.aextract_data(F.transform_query({'dataflows':value})))
        self.assertEqual({r['dataflow_id'] for r in rows},{'CPI','PCPS'})
        self.assertEqual(len(rows),139)
        self.assertTrue(all(r['indicator'] for r in rows))

class RouteShape(unittest.TestCase):
    def test_real_asgi_query_returns_both_cached_flow_indicators(self):
        from fastapi.testclient import TestClient
        from openbb_core.api.rest_api import app
        with patch('openbb_core.provider.utils.helpers.make_request',side_effect=AssertionError('No network permitted')):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                client=TestClient(app)
                for params in [
                    {'provider':'imf','dataflows':'CPI,PCPS'},
                    [('provider','imf'),('dataflows','CPI'),('dataflows','PCPS')],
                    {'provider':'imf','dataflows':' CPI ; PCPS '},
                ]:
                    with self.subTest(params=params):
                        response=client.get('/api/v1/imf/available_indicators',params=params)
                        self.assertEqual(response.status_code,200)
                        rows=response.json()['results']
                        self.assertEqual(len(rows),139)
                        self.assertEqual({r['dataflow_id'] for r in rows},{'CPI','PCPS'})

if __name__=='__main__':unittest.main(verbosity=2)
