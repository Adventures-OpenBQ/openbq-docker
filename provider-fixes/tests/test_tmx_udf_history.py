"""Installed UDF protocol semantics, with only GraphQL transport stubbed."""
from datetime import datetime,timezone
import math
import unittest
from unittest.mock import AsyncMock,patch
from openbb_tmx.routers.udf import history,_instrument_type


def stamp(day,hour=0):return int(datetime(2026,11,day,hour,tzinfo=timezone.utc).timestamp())
def bar(day,**changes):return dict(dateTime=f'2026-11-{day:02d}T05:00:00+00:00',open=10.,high=12.,low=9.,close=11.,volume=100.,**changes) if not changes else {**bar(day),**changes}


class HistorySemantics(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,bars,**kwargs):
        transport=AsyncMock(return_value={'getTimeSeriesData':bars})
        with patch('openbb_tmx.utils.cache.amake_gql_request',transport):
            result=await history(symbol='AC',resolution='D',to=kwargs.get('to',stamp(10)),from_=kwargs.get('from_',stamp(2)),countback=kwargs.get('countback'))
        return result,transport

    async def test_requested_date_window_is_inclusive_from_exclusive_to(self):
        result,transport=await self.exercise([bar(d) for d in range(1,11)],from_=stamp(3),to=stamp(7))
        self.assertEqual(result['t'],[stamp(d) for d in range(3,7)])
        variables=transport.call_args.args[2]
        self.assertEqual(variables['start'],'2026-11-03');self.assertEqual(variables['end'],'2026-11-07')

    async def test_countback_overrides_from_and_returns_latest_before_to(self):
        result,_=await self.exercise([bar(d) for d in range(1,11)],from_=stamp(8),to=stamp(10),countback=3)
        self.assertEqual(result['t'],[stamp(7),stamp(8),stamp(9)])
        self.assertEqual(len(result['c']),3)

    async def test_period_bar_time_is_utc_midnight(self):
        result,_=await self.exercise([bar(3)])
        self.assertEqual(result['t'],[stamp(3)])

    async def test_empty_window_is_explicit_no_data(self):
        result,_=await self.exercise([bar(1)],from_=stamp(3),to=stamp(7))
        self.assertEqual(result,{'s':'no_data'})

    async def test_invalid_mandatory_close_is_not_a_bar(self):
        result,_=await self.exercise([bar(3,close=float('nan')),bar(4),bar(5,close=None)])
        self.assertEqual(result['c'],[11.]);self.assertEqual(result['t'],[stamp(4)])

    async def test_missing_optional_price_column_is_omitted_without_losing_closes(self):
        result,_=await self.exercise([bar(3,high=None),bar(4)])
        self.assertNotIn('h',result)
        self.assertEqual(result['c'],[11.,11.]);self.assertFalse(set(result)&{'o','h','l'})

    async def test_real_close_only_feed_is_preserved_without_fake_ohlc(self):
        result,_=await self.exercise([bar(3,open=None,high=None,low=None)])
        self.assertEqual(result['c'],[11.]);self.assertFalse(set(result)&{'o','h','l'})

    async def test_upstream_error_is_explicit_not_success(self):
        with patch('openbb_tmx.utils.cache.amake_gql_request',AsyncMock(side_effect=TimeoutError)):
            result=await history('AC','D',stamp(10),stamp(2),None)
        self.assertEqual(result['s'],'error')

    def test_etf_maps_to_fund_protocol_type(self):
        self.assertEqual(_instrument_type('XIU','ETF'),'fund')


if __name__=='__main__':unittest.main(verbosity=2)
