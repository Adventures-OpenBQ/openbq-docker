import asyncio
import unittest
import pandas
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from openbb_sec.utils.parse_13f import parse_13f_hr
from openbb_sec.models.sec_filing import SecBaseFiling
from openbb_sec.utils.xbrl_taxonomy_helper import get_label_url_for_import, TAXONOMIES
from openbb_deribit.utils import helpers
from openbb_deribit.models import options_chains as chains


def filing(optional=True, prefix='', value=1000):
    extra = '<shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><votingAuthority><Sole>10</Sole><Shared>0</Shared><None>0</None></votingAuthority>' if optional else ''
    return f'''<SEC-DOCUMENT>COMPANY NAME: AT&T\n<DOCUMENT><XML><?xml version="1.0"?><edgarSubmission><headerData><filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo></headerData></edgarSubmission></XML></DOCUMENT><DOCUMENT><XML><?xml version="1.0"?><{prefix}informationTable xmlns:ns2="test"><{prefix}infoTable><nameOfIssuer>S&amp;P &#65;</nameOfIssuer><titleOfClass>COM &amp; CL</titleOfClass><cusip>123</cusip><value>{value}</value><investmentDiscretion>SOLE</investmentDiscretion>{extra}</{prefix}infoTable></{prefix}informationTable></XML></DOCUMENT></SEC-DOCUMENT>'''

class Ports(unittest.TestCase):
    def test_optional_fields(self):
        row=asyncio.run(parse_13f_hr(filing(False)))[0]
        self.assertEqual(row['weight'],1)
        self.assertEqual(row['nameOfIssuer'],'S&P A')
    def test_namespaced_sgml_entities(self):
        row=asyncio.run(parse_13f_hr(filing(prefix='ns2:')))[0]
        self.assertEqual(row['nameOfIssuer'],'S&P A')
        self.assertEqual(row['titleOfClass'],'COM & CL')
    def test_zero_value_existing_guard(self):
        self.assertEqual(asyncio.run(parse_13f_hr(filing(value=0)))[0]['weight'],0.0)
    def test_sec_headers(self):
        for host in ['www.sec.gov','xbrl.sec.gov']:
            async def capture(url, **kwargs): return kwargs['headers']
            with patch('openbb_sec.utils.cache.cached_request',capture):
                headers=asyncio.run(SecBaseFiling._adownload_file(f'https://{host}/test'))
            self.assertEqual(any(k.lower()=='host' for k in headers),host=='www.sec.gov')
    def test_current_and_legacy_labels(self):
        for tax in ['country','currency','exch','naics','sic','stpr','snj','dei']:
            suffix=f'{tax}-entire-2025.xsd' if tax not in ['snj','dei'] else f'{tax}-2025'+('_doc.xsd' if tax=='snj' else '_lab.xsd')
            self.assertEqual(get_label_url_for_import(f'https://xbrl.sec.gov/{tax}/2025/{tax}-2025.xsd'),f'https://xbrl.sec.gov/{tax}/2025/{suffix}')
            self.assertEqual(get_label_url_for_import(f'https://xbrl.sec.gov/{tax}/2020/{tax}-2020-01-31.xsd'),f'https://xbrl.sec.gov/{tax}/2020/{tax}-lab-2020-01-31.xml')
    def test_cross_host_user_agent_fallback(self):
        from openbb_sec.utils import definitions
        async def capture(url, **kwargs): return kwargs['headers']
        with patch.dict(definitions.SEC_HEADERS, {'User-Agent':'definitelynot@fakecompany.com'}), patch.dict(definitions.HEADERS, {'User-Agent':'Example Co example@example.com'}), patch('openbb_sec.utils.cache.cached_request',capture):
            headers=asyncio.run(SecBaseFiling._adownload_file('https://xbrl.sec.gov/test'))
            self.assertEqual(headers['User-Agent'],'Example Co example@example.com')
            self.assertEqual(definitions.SEC_HEADERS['User-Agent'],'definitelynot@fakecompany.com')
    def test_reference_schema_label_discovery(self):
        from io import BytesIO
        from openbb_sec.utils.xbrl_taxonomy_helper import XBRLManager
        manager=XBRLManager()
        url='https://xbrl.sec.gov/country/2025/country-entire-2025.xsd'
        def find(base,*parts): return url if parts==('country-entire-','2025','.xsd') else None
        with patch.object(manager.client,'find_file',side_effect=find) as lookup, patch.object(manager.client,'fetch_file',return_value=BytesIO(b'<schema/>')):
            manager._ensure_labels('country',2025)
        self.assertEqual(lookup.call_args_list[0].args[1:],('country-entire-','2025','.xsd'))
    def test_analysis_rows_use_exact_whole_days(self):
        from openbb_deribit.utils.options.chain import _rows
        class Frozen(datetime):
            @classmethod
            def now(cls,tz=None): return cls(2026,9,20,8,tzinfo=timezone.utc)
        spec={'option_type':'call','strike':1,'expiration_timestamp':1789977600000}
        with patch('datetime.datetime',Frozen):
            row=_rows([{'instrument_name':'test'}],{'test':spec},1)[0]
        self.assertEqual(row['dte'],1)
    def test_whole_expiry_days(self):
        self.assertTrue(hasattr(helpers,'days_to_expiration'))
        for hours,days in [(5,0),(23.99,0),(24,1),(47,1),(720,30),(-1,0)]:
            self.assertEqual(helpers.days_to_expiration(1789977600000,1789977600000-hours*3600000),days)
    def test_chain_exchange_instant_and_fallback(self):
        symbol='XRP_USDC-21SEP26-1-C'
        class Frozen(datetime):
            @classmethod
            def now(cls,tz=None): return cls(2026,9,20,9,tzinfo=timezone.utc)
        real_to_datetime=pandas.to_datetime
        def frozen_to_datetime(value,*args,**kwargs):
            return pandas.Timestamp('2026-09-20 09:00:00') if isinstance(value,str) and value=='today' else real_to_datetime(value,*args,**kwargs)
        for spec in [{'instrument_name':symbol,'expiration_timestamp':1789977600000}, {'instrument_name':symbol}]:
            with patch('pandas.to_datetime',frozen_to_datetime), patch.object(chains,'datetime',Frozen), patch.object(helpers,'get_options_symbols',AsyncMock(return_value={'exp':[symbol]})), patch.object(helpers,'get_instruments',AsyncMock(return_value=[spec])), patch('openbb_deribit.utils.websocket.subscribe_tickers',AsyncMock(return_value={symbol:{'timestamp':1789894800000}})):
                rows=asyncio.run(chains.DeribitOptionsChainsFetcher.aextract_data(chains.DeribitOptionsChainsQueryParams(symbol='XRP_USDC'),{}))
            self.assertEqual(rows[0]['dte'],0)

if __name__=='__main__': unittest.main(verbosity=2)
