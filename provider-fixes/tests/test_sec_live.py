import csv,io,unittest,zipfile
from datetime import date
from unittest.mock import AsyncMock,patch
from openbb_sec.models import adviser_universe as adv
from openbb_sec.models.sic_search import SecSicSearchFetcher,SecSicSearchQueryParams
from openbb_core.app.model.abstract.error import OpenBBError

def archive(rows, columns=None):
    columns=columns or ['Organization CRD#','SEC#','Firm Type','Primary Business Name','Legal Name','SEC Current Status','Latest ADV Filing Date']
    text=io.StringIO();writer=csv.DictWriter(text,fieldnames=columns);writer.writeheader();writer.writerows(rows)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr('report.csv',text.getvalue().encode('cp1252'))
    return output.getvalue()

def row(crd='2288',sec=''):
    return {'Organization CRD#':crd,'SEC#':sec,'Firm Type':'Registered','Primary Business Name':'INGALLS INVESTMENT MANAGEMENT, LLC','Legal Name':'INGALLS INVESTMENT MANAGEMENT, LLC','SEC Current Status':'Approved','Latest ADV Filing Date':'07/06/2026'}

class Adviser(unittest.TestCase):
    def setUp(self):self.report=adv.AdviserReport('registered',date(2026,9,1),'application/zip','https://www.sec.gov/report.zip')
    def test_blank_source_sec_number_retains_adviser_and_other_records(self):
        rows=adv._parse_report(archive([row('100','801-1'),row(),row('300','801-3')]),self.report)
        self.assertEqual([r['crd'] for r in rows],['100','2288','300'])
        models=adv.SecAdviserUniverseFetcher.transform_data(adv.SecAdviserUniverseQueryParams(registration_type='registered'),rows)
        self.assertEqual([m.sec_number for m in models],['801-1',None,'801-3'])
        self.assertEqual(models[1].latest_adv_filing_date,date(2026,7,6))
    def test_crd_filter_can_return_blank_sec_number_without_invention(self):
        rows=adv._parse_report(archive([row('100','801-1'),row()]),self.report,'2288')
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['sec_number'])
    def test_missing_crd_still_rejected(self):
        with self.assertRaises(OpenBBError):adv._parse_report(archive([row('','801-1')]),self.report)
    def test_missing_sec_column_still_rejected(self):
        r=row();del r['SEC#']
        with self.assertRaises(OpenBBError):adv._parse_report(archive([r],list(r)),self.report)

class SIC(unittest.IsolatedAsyncioTestCase):
    async def check_table(self,heading):
        html='<html><body><table><tr>'+''.join('<'+heading+'>'+s+'</'+heading+'>' for s in ['SIC Code','Office','Industry Title'])+'</tr><tr><td>7372</td><td>Office of Technology</td><td>Services-Prepackaged Software</td></tr><tr><td>1000</td><td>Office of Energy</td><td>Metal Mining</td></tr></table></body></html>'
        with patch('openbb_sec.utils.cache.cached_request',new=AsyncMock(return_value=html)):
            query=SecSicSearchQueryParams(query='software')
            raw=await SecSicSearchFetcher.aextract_data(query,None)
            models=SecSicSearchFetcher.transform_data(query,raw)
        self.assertEqual(len(models),1);self.assertEqual(models[0].sic,7372);self.assertEqual(models[0].industry,'Services-Prepackaged Software')
    async def test_current_td_header_is_not_treated_as_business_row(self):await self.check_table('td')
    async def test_original_th_header_still_preserved(self):await self.check_table('th')
