import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pydantic import SecretStr
from openbb_bls import bls_provider
from openbb_bls.models.series import BlsSeriesFetcher
from openbb_core.provider.query_executor import QueryExecutor

class AnonymousSeries(unittest.TestCase):
    def execute(self,params,credentials):
        payloads=[]
        async def transport(**kwargs):
            data=json.loads(kwargs['data']);payloads.append(data)
            return {'Results':{'series':[{'seriesID':data['seriesid'][0],'data':[{'year':str(data['endyear']),'period':'M01','periodName':'January','value':'315.605','footnotes':[]}]}]},'message':[]}
        executor=QueryExecutor(registry=SimpleNamespace(providers={'bls':bls_provider}))
        with patch('openbb_core.provider.utils.helpers.amake_request',transport):
            result=asyncio.run(executor.execute('bls','BlsSeries',params,credentials=credentials))
        return result,payloads
    def test_no_key_reaches_real_helper_and_omits_registration(self):
        result,payloads=self.execute({'symbol':'CUUR0000SA0','start_date':'2025-01-01','end_date':'2025-12-31'}, {})
        self.assertEqual(len(result.result),1)
        self.assertEqual(result.result[0].symbol,'CUUR0000SA0')
        self.assertEqual(len(payloads),1)
        self.assertNotIn('registrationkey',payloads[0])
    def test_provided_key_still_reaches_registered_payload(self):
        # Deliberately synthetic marker, never an environment/registered secret.
        marker='synthetic-unit-test-marker'
        result,payloads=self.execute({'symbol':'CUUR0000SA0','start_date':'2025-01-01','end_date':'2025-12-31'}, {'bls_api_key':SecretStr(marker)})
        self.assertEqual(len(result.result),1)
        self.assertTrue(all(p.get('registrationkey')==marker for p in payloads))
    def test_anonymous_retains_25_symbol_10_year_chunks(self):
        _,payloads=self.execute({'symbol':','.join('TEST'+str(i) for i in range(26)),'start_date':'2005-01-01','end_date':'2025-12-31'}, {})
        self.assertEqual(len(payloads),6)
        self.assertEqual(max(len(p['seriesid']) for p in payloads),25)
        self.assertEqual(max(p['endyear']-p['startyear']+1 for p in payloads),10)
        self.assertTrue(all('registrationkey' not in p for p in payloads))
    def test_registered_retains_50_symbol_20_year_chunks(self):
        _,payloads=self.execute({'symbol':','.join('TEST'+str(i) for i in range(51)),'start_date':'2005-01-01','end_date':'2025-12-31'}, {'bls_api_key':SecretStr('synthetic-unit-test-marker')})
        self.assertEqual(len(payloads),4)
        self.assertEqual(max(len(p['seriesid']) for p in payloads),50)
        self.assertEqual(max(p['endyear']-p['startyear']+1 for p in payloads),20)

if __name__=='__main__':unittest.main(verbosity=2)
