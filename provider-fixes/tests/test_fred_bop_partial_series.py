"""Real BOP and series fetchers over real amake_request/aiohttp/diskcache."""
import copy
import datetime
import json
import time
import unittest
from aiohttp import web
import test_fred_cache_recovery as cache_tests
from openbb_fred.models.balance_of_payments import FredBalanceOfPaymentsFetcher as BOP
from openbb_fred.utils import cache
from openbb_fred.utils.fred_helpers import get_bop_series

MISSING='USAB6BLTT02STSAQ'
MISSING_ERROR={'error_code':400,'error_message':'Bad Request. The series does not exist.'}
METADATA={'title':'Synthetic BOP financial measure','units':'Millions of U.S. Dollars','frequency':'Quarterly','seasonal_adjustment':'Seasonally Adjusted','notes':'Offline loopback fixture only'}

class BOPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await cache_tests.FredCacheTests.asyncSetUp(self)
        self.unavailable={MISSING}
        self.requested=[]

    asyncTearDown=cache_tests.FredCacheTests.asyncTearDown

    async def serve(self,request):
        sid=request.query.get('series_id')
        self.calls.append(time.monotonic())
        self.requested.append({'path':request.path,'series_id':sid})
        if sid in self.unavailable:
            return web.json_response(MISSING_ERROR,status=400)
        if request.path=='/fred/series':
            return web.json_response({'seriess':[dict(METADATA,id=sid)]})
        value='-125.5' if sid=='USAB6BLTT01CXCUSAQ' else '100.25'
        rows=[{'date':'2024-01-01','value':value,'realtime_start':'2024-01-01','realtime_end':'2024-12-31'},
              {'date':'2024-04-01','value':value,'realtime_start':'2024-01-01','realtime_end':'2024-12-31'}]
        return web.json_response({'observations':rows,'count':2,'offset':0,'limit':100000})

    async def report(self):
        query=BOP.transform_query({'country':'united_states','use_cache':True})
        data=await BOP.aextract_data(query,{'fred_api_key':'offline-fixture'})
        return BOP.transform_data(query,data).result

    async def test_bop_default_preserves_available_measures_when_one_optional_series_is_400(self):
        rows=await self.report()
        self.assertEqual(len(rows),2)
        self.assertEqual({r.period for r in rows},{datetime.date(2024,1,1),datetime.date(2024,4,1)})
        self.assertTrue(all(r.balance_total==-125.5 for r in rows))
        self.assertTrue(all(r.balance_percent_of_gdp is None for r in rows))
        self.assertEqual({r['series_id'] for r in self.requested},set(get_bop_series('USA').values()))

    async def test_bop_unavailable_series_errors_are_not_cached_and_warm_valid_siblings_are_reused(self):
        await self.report()
        self.assertEqual(cache.stats()['items'],38)
        self.assertEqual(len(self.requested),40)
        await self.report()
        self.assertEqual(len(self.requested),42)
        self.assertEqual(cache.stats()['items'],38)
        self.assertTrue(all(r['series_id']==MISSING for r in self.requested[-2:]))

    async def test_bop_all_available_series_cold_and_warm_remain_complete(self):
        self.unavailable=set()
        rows=await self.report()
        self.assertTrue(all(r.balance_percent_of_gdp==100.25 for r in rows))
        self.assertEqual(len(self.requested),40)
        rows=await self.report()
        self.assertEqual(len(rows),2)
        self.assertEqual(len(self.requested),40)
        self.assertEqual(cache.stats()['items'],40)

if __name__=='__main__':unittest.main(verbosity=2)
