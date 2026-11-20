from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch
from zipfile import BadZipFile
from test_ffiec_remaining_review import wired,CYCLE,ROOT
from openbb_federal_reserve.utils import executive_summary_report as esr,ubpr_report as ubpr
from openbb_federal_reserve.models import peer_group_bank as bank
from openbb_core.app.model.abstract.error import OpenBBError
class Controls(TestCase):
 def test_esr_headings_and_nulls_do_not_request_units(self):
  raw=[{'linecaption':'#SectionTitle#Heading','conceptname':'','09_30_2026':''},{'linecaption':'No Data','conceptname':'UNRESOLVED','09_30_2026':None}]
  with wired() as s:
   source=s.enter_context(patch(ROOT+'cdr.fetch_taxonomy',side_effect=AssertionError('must not request units for no numeric values')))
   s.enter_context(patch.object(esr,'report_cycles',return_value=[CYCLE]))
   s.enter_context(patch.object(esr,'report_sections',return_value=[{'sectionid':'A'}]))
   s.enter_context(patch.object(esr,'_post',return_value=raw))
   rows=esr.fetch_executive_summary('852218')
  self.assertEqual(len(rows),2);self.assertTrue(all(r['is_header'] for r in rows));source.assert_not_called()
 def run_bank(self,raw,taxonomy=b'valid',parsed=None):
  with wired() as s:
   s.enter_context(patch(ROOT+'cdr.fetch_taxonomy',side_effect=taxonomy if isinstance(taxonomy,Exception) else None,return_value=taxonomy))
   s.enter_context(patch(ROOT+'cdr.parse_taxonomy',return_value=parsed or [{'mdrm':'MONEY','data_type':'Monetary'}]))
   s.enter_context(patch.object(bank,'_page_id',return_value=('1','Summary Ratios')))
   s.enter_context(patch.object(bank,'_peer_group_name',return_value=('1','peers')))
   s.enter_context(patch.object(bank,'_peer_group_banks',return_value=[{'rssd':'852218','name':'Bank'}]))
   s.enter_context(patch.object(ubpr,'report_cycles',return_value=[CYCLE]))
   s.enter_context(patch.object(ubpr,'_post',side_effect=lambda request,args:[{'sectionid':'1'}] if request=='MBReportPageSections' else raw))
   return bank.fetch_peer_group_bank_report('852218','Summary Ratios')['rows']
 def test_unknown_explicit_type_rejected_despite_valid_taxonomy(self):
  with self.assertRaisesRegex(OpenBBError,'Unknown.*999'):
   self.run_bank([{'conceptname':'MONEY','datatypeid':'999','linecaption':'Assets','09_852218':'10'}])
 def test_conflicting_explicit_types_rejected(self):
  with self.assertRaisesRegex(OpenBBError,'Conflicting.*MONEY'):
   self.run_bank([{'conceptname':'MONEY','datatypeid':kind,'linecaption':'Assets','09_852218':'10'} for kind in ['9','96']])
 def test_unresolved_missing_type_rejected_when_taxonomy_invalid(self):
  with self.assertRaisesRegex(OpenBBError,'datatype'):
   self.run_bank([{'conceptname':'MONEY','linecaption':'Assets','09_852218':'10'}],BadZipFile())
 def test_explicit_source_type_retains_priority(self):
  rows=self.run_bank([{'conceptname':'MONEY','datatypeid':'9','linecaption':'Assets','09_852218':'10'}],parsed=[{'mdrm':'MONEY','data_type':'Ratio'}])
  self.assertEqual(rows[0]['Bank (852218)'],10000)
