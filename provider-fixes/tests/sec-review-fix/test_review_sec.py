import asyncio
import re
import unittest
from unittest.mock import AsyncMock, patch
from openbb_sec.utils import parse_13f
from test_ports import filing

class ReviewSEC(unittest.TestCase):
    def test_fully_prefixed_children_and_header(self):
        text=filing()
        text=re.sub(r'<(/?)([a-zA-Z]+)(?=[ >])',r'<\1arbitrary_ns:\2',text)
        rows=asyncio.run(parse_13f.parse_13f_hr(text))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['nameOfIssuer'],'S&P A')
        self.assertEqual(rows[0]['value'],1000)
        self.assertEqual(rows[0]['weight'],1.)
    def test_mixed_optional_rows_preserve_distinct_holdings(self):
        simple=re.search(r'<infoTable>.*?</infoTable>',filing(False)).group().replace('123','456').replace('<value>1000</value>','<value>3000</value>')
        text=filing().replace('</informationTable>',simple+'</informationTable>')
        rows=asyncio.run(parse_13f.parse_13f_hr(text))
        rows={r['cusip']:r for r in rows}
        self.assertEqual(set(rows),{'123','456'})
        self.assertEqual((rows['123']['value'],rows['456']['value']),(1000,3000))
        self.assertEqual((rows['123']['weight'],rows['456']['weight']),(.25,.75))
        self.assertEqual(rows['123']['principal_amount'],10)
    def test_missing_grouping_fields_keep_row(self):
        simple=re.search(r'<infoTable>.*?</infoTable>',filing()).group().replace('123','456').replace('<titleOfClass>COM &amp; CL</titleOfClass>','').replace('<investmentDiscretion>SOLE</investmentDiscretion>','')
        text=filing().replace('</informationTable>',simple+'</informationTable>')
        rows=asyncio.run(parse_13f.parse_13f_hr(text))
        self.assertEqual({r['cusip'] for r in rows},{'123','456'})
        self.assertEqual(sum(r['value'] for r in rows),2000)
        self.assertEqual([r['weight'] for r in rows],[.5,.5])
    def test_url_cache_hit_and_miss_preserved(self):
        url='https://www.sec.gov/Archives/example.txt'
        with patch('openbb_sec.utils.cache.aget_cached',AsyncMock(return_value=None)) as get, patch('openbb_sec.utils.cache.aset_cached',AsyncMock()) as put, patch.object(parse_13f,'get_complete_submission',AsyncMock(return_value=filing())) as fetch:
            result=asyncio.run(parse_13f.parse_13f_hr(url))
            get.assert_awaited_once_with(f'GET {url} ::13f-parsed')
            put.assert_awaited_once_with(f'GET {url} ::13f-parsed',result)
            fetch.assert_awaited_once_with(url)
        with patch('openbb_sec.utils.cache.aget_cached',AsyncMock(return_value=result)), patch.object(parse_13f,'get_complete_submission',AsyncMock()) as fetch:
            self.assertEqual(asyncio.run(parse_13f.parse_13f_hr(url)),result)
            fetch.assert_not_awaited()
