import io,zipfile,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from openbb_federal_reserve.utils import cdr
from openbb_core.app.model.abstract.error import OpenBBError

def archive():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('ubpr-concepts.xsd','<schema><element name="UBPR1234" type="xbrli:monetaryItemType" xbrli:periodType="instant" /></schema>')
    return out.getvalue()

class Taxonomy(unittest.TestCase):
    def test_invalid_source_not_cached(self):
        saved=[]
        def cached(key,ttl,producer):
            data=producer();saved.append(data);return data
        session=Mock();session.get.return_value=SimpleNamespace(text='');session.post.return_value=SimpleNamespace(text='',content=b'<?xml version="1.0"?><schema><element name="pres-root"/></schema>')
        with patch.object(cdr,'_get_session',return_value=session),patch('openbb_federal_reserve.utils.cache.cached',cached):
            with self.assertRaisesRegex(zipfile.BadZipFile,'FFIEC.*taxonomy.*ZIP'):
                cdr.fetch_taxonomy('ubpr_ratio_single')
        self.assertEqual(saved,[])
    def test_parse_corrupt_archive_actionable(self):
        with self.assertRaises(zipfile.BadZipFile):
            cdr.parse_taxonomy(b'<html>source failure</html>')
    def test_valid_taxonomy_preserves_types(self):
        self.assertEqual(cdr.parse_taxonomy(archive()),[{'mdrm':'UBPR1234','data_type':'Monetary','period_type':'instant','balance':None}])
    def test_poisoned_old_key_bypassed(self):
        keys=[]
        def cached(key,ttl,producer):
            keys.append(key)
            return b'old invalid content' if key==('cdr_taxonomy','ubpr_ratio_single','') else producer()
        session=Mock();session.get.return_value=SimpleNamespace(text='');session.post.return_value=SimpleNamespace(text='',content=archive())
        with patch.object(cdr,'_get_session',return_value=session),patch('openbb_federal_reserve.utils.cache.cached',cached):
            self.assertEqual(cdr.fetch_taxonomy('ubpr_ratio_single'),archive())
        self.assertNotEqual(keys[0],('cdr_taxonomy','ubpr_ratio_single',''))
if __name__=='__main__':unittest.main(verbosity=2)
