import unittest,zipfile,warnings
from unittest.mock import patch
from openbb_federal_reserve.utils.concepts import concept_index
class Concepts(unittest.TestCase):
    def get_index(self,cell):
        with patch('openbb_federal_reserve.utils.cache.cached',side_effect=lambda key,ttl,producer:producer()),patch('openbb_federal_reserve.utils.cdr.fetch_taxonomy',return_value=b'<schema/>'),patch('openbb_federal_reserve.utils.ubpr_report._section_id',return_value=('502574','Summary Ratios')),patch('openbb_federal_reserve.utils.ubpr_report.report_cycles',return_value=[{'reportingcycleid':'154'}]),patch('openbb_federal_reserve.utils.ubpr_report._post',return_value=[{'09_30_2026':cell}]) as router,patch('openbb_federal_reserve.utils.mdrm.fetch_mdrm_dictionary',return_value={'UBPRD659':'TOTAL ASSETS'}),patch('openbb_federal_reserve.utils.mdrm.fetch_mdrm_definitions',return_value={'UBPRD659':'Actual official definition'}):
            result=concept_index('ubpr_ratio_single',section='Summary Ratios')
            self.assertEqual(router.call_args.args[1]['ScheduleID'],'502574')
            self.assertEqual(router.call_args.args[1]['ReportingCycleIdList'],'154')
            return result
    def test_invalid_taxonomy_uses_report_cdr_types(self):
        with self.assertWarnsRegex(UserWarning,'taxonomy.*report'):
            result=self.get_index("10;UBPRD659;9;0;'', 1.25;UBPRE001;96;2;'', 2;UBPACOUNT;11;0;'', text;UBPRTEXT;10;0;''")
        self.assertTrue(result['UBPRD659']['monetary'])
        self.assertEqual(result['UBPRD659']['name'],'Total Assets')
        self.assertEqual(result['UBPRD659']['narrative'],'Actual official definition')
        self.assertFalse(result['UBPRE001']['monetary'])
        self.assertFalse(result['UBPACOUNT']['monetary'])
        self.assertTrue(result['UBPRTEXT']['is_text'])
        self.assertEqual(10*(1000 if result['UBPRD659']['monetary'] else 1),10000)
        self.assertEqual(1.25*(1000 if result['UBPRE001']['monetary'] else 1),1.25)
    def test_valid_taxonomy_does_not_fetch_report_metadata(self):
        with patch('openbb_federal_reserve.utils.cache.cached',side_effect=lambda key,ttl,producer:producer()),patch('openbb_federal_reserve.utils.cdr.fetch_taxonomy',return_value=b'zip'),patch('openbb_federal_reserve.utils.cdr.parse_taxonomy',return_value=[{'mdrm':'UBPRD659','data_type':'Monetary'}]),patch('openbb_federal_reserve.utils.ubpr_report._post') as router,patch('openbb_federal_reserve.utils.mdrm.fetch_mdrm_dictionary',return_value={}),patch('openbb_federal_reserve.utils.mdrm.fetch_mdrm_definitions',return_value={}):
            index=concept_index('ubpr_ratio_single',section='Summary Ratios')
        self.assertTrue(index['UBPRD659']['monetary'])
        router.assert_not_called()
    def test_missing_type_fails(self):
        with self.assertRaisesRegex(Exception,'Unknown.*datatype'):
            self.get_index('1;UBPRD659')
    def test_missing_concept_type_fails(self):
        from openbb_federal_reserve.utils.concepts import _report_concept_types
        with patch('openbb_federal_reserve.utils.ubpr_report._section_id',return_value=('502574','Summary Ratios')),patch('openbb_federal_reserve.utils.ubpr_report.report_cycles',return_value=[{'reportingcycleid':'154'}]),patch('openbb_federal_reserve.utils.ubpr_report._post',return_value=[]):
            with self.assertRaisesRegex(Exception,'no explicit concept datatypes'):
                _report_concept_types('Summary Ratios')
    def test_unknown_type_fails(self):
        with self.assertRaisesRegex(Exception,'Unknown.*999'):
            self.get_index("1;UBPRD659;999;0;''")
    def test_nonubpr_invalid_taxonomy_not_reinterpreted(self):
        with patch('openbb_federal_reserve.utils.cache.cached',side_effect=lambda key,ttl,producer:producer()),patch('openbb_federal_reserve.utils.cdr.fetch_taxonomy',return_value=b'<schema/>'):
            with self.assertRaises(zipfile.BadZipFile):concept_index('call_single')
if __name__=='__main__':unittest.main(verbosity=2)
