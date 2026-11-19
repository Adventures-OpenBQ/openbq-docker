import unittest,zipfile
from contextlib import ExitStack
from unittest.mock import patch
from openbb_federal_reserve.utils import ubpr_report as ubpr,executive_summary_report as esr,custom_peer_group as custom
from openbb_federal_reserve.models import peer_group_bank as peer
from openbb_core.app.model.abstract.error import OpenBBError
ROOT='openbb_federal_reserve.utils.'
RAW=[{'linecaption':'assets','lineid':'1','linedisplayorder':'1','09_30_2026':"10;MONEY;9;0;'', 1.25;UBPSTYPE;96;2;'', 29;UBPKTYPE;11;0;''",'03_31_2001':"1.25;RATIO;96;2;'', 2.5;UBPSTYPE;96;2;'', 30;UBPKTYPE;11;0;''"}]
class Remaining(unittest.TestCase):
 def wire(self,stack):
  stack.enter_context(patch(ROOT+'cache.cached',side_effect=lambda key,ttl,producer:producer()))
  stack.enter_context(patch(ROOT+'cdr.fetch_taxonomy',side_effect=zipfile.BadZipFile('source unavailable')))
  stack.enter_context(patch(ROOT+'mdrm.fetch_mdrm_dictionary',return_value={}))
  stack.enter_context(patch(ROOT+'mdrm.fetch_mdrm_definitions',return_value={}))
  stack.enter_context(patch(ROOT+'guide.fetch_guide_concepts',return_value={}))
 def test_ubpr_actual_cells_all_periods_keep_historical_units(self):
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch.object(ubpr,'_section_id',return_value=('1','Summary Ratios')))
   s.enter_context(patch.object(ubpr,'report_cycles',return_value=[{'reportingcycleid':'154'},{'reportingcycleid':'10'}]))
   s.enter_context(patch.object(ubpr,'_post',return_value=RAW))
   rows=ubpr.fetch_ubpr_section('852218','Summary Ratios',all_periods=True)['rows']
  self.assertEqual(rows[0]['2026-09-30'],10000)
  self.assertEqual(rows[0]['2001-03-31'],1.25)
 def test_ubpr_bank_and_peer_units_independent(self):
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch.object(ubpr,'_section_id',return_value=('1','Summary Ratios')))
   s.enter_context(patch.object(ubpr,'report_cycles',return_value=[{'reportingcycleid':'154'}]))
   s.enter_context(patch.object(ubpr,'_post',return_value=RAW))
   rows=ubpr.fetch_ubpr_section('852218','Summary Ratios')['rows']
  self.assertEqual(rows[0]['2026-09-30 Bank'],10000)
  self.assertEqual(rows[0]['2026-09-30 PG'],1.25)
  self.assertEqual(rows[0]['2026-09-30 PCT'],29)
 def test_executive_summary_actual_datatype_scales(self):
  raw=[{'conceptname':'MONEY','datatypeid':'9','linecaption':'assets','lineid':'1','09_30_2026':'10'},{'conceptname':'RATIO','datatypeid':'96','linecaption':'ratio','lineid':'2','09_30_2026':'1.25'}]
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch.object(esr,'report_sections',return_value=[{'sectionid':'1'}]))
   s.enter_context(patch.object(esr,'report_cycles',return_value=[{'reportingcycleid':'154','enddateformatted':'09/30/2026'}]))
   s.enter_context(patch.object(esr,'_post',return_value=raw))
   rows=esr.fetch_executive_summary('852218')
  self.assertEqual([r['2026-09-30'] for r in rows],[10000,1.25])
 def test_custom_uses_actual_target_and_requested_window(self):
  rows=[{'label':'assets','concept':'MONEY','2026-09-30 Bank':10.0},{'label':'ratio','concept':'RATIO','2026-09-30 Bank':1.25}]
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch.object(ubpr,'_section_id',return_value=('1','Summary Ratios')))
   post=s.enter_context(patch.object(ubpr,'_post',return_value=RAW))
   result=custom._enrich(rows,section='Summary Ratios',cycle_ids='154,10',rssd_id='451965')
  self.assertEqual([r['2026-09-30 Bank'] for r in result],[10000,1.25])
  self.assertEqual(post.call_args.args[1]['ID_RSSD'],'451965')
  self.assertEqual(post.call_args.args[1]['ReportingCycleIdList'],'154,10')
 def test_peer_bank_actual_source_type_scales(self):
  raw=[{'conceptname':'MONEY','datatypeid':'9','linecaption':'assets','09_852218':'10'}]
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch.object(peer,'_page_id',return_value=('1','Summary Ratios')))
   s.enter_context(patch.object(peer,'_peer_group_name',return_value=('1','peers')))
   s.enter_context(patch.object(peer,'_peer_group_banks',return_value=[{'rssd':'852218','name':'Bank'}]))
   s.enter_context(patch.object(ubpr,'report_cycles',return_value=[{'reportingcycleid':'154','enddateformatted':'09/30/2026'}]))
   s.enter_context(patch.object(ubpr,'_post',side_effect=lambda requestor,criteria:[{'sectionid':'1'}] if requestor=='MBReportPageSections' else raw))
   result=peer.fetch_peer_group_bank_report('852218','Summary Ratios')
  self.assertEqual(result['rows'][0]['Bank (852218)'],10000)
 def test_custom_historical_layout_change_rejected(self):
  with self.assertRaisesRegex(OpenBBError,'layout|concept'):
   custom._merge_batches([[{'label':'assets','concept':'MONEY','2026-09-30 Bank':10.0}],[{'label':'ratio','concept':'RATIO','2001-03-31 Bank':1.25}]])
 def test_valid_taxonomy_does_not_require_report_datatypes(self):
  raw=[{'linecaption':'assets','09_30_2026':"10;MONEY"}]
  with ExitStack() as s:
   self.wire(s)
   s.enter_context(patch(ROOT+'cdr.fetch_taxonomy',return_value=b'valid'))
   s.enter_context(patch(ROOT+'cdr.parse_taxonomy',return_value=[{'mdrm':'MONEY','data_type':'Monetary'}]))
   s.enter_context(patch.object(ubpr,'_section_id',return_value=('1','Summary Ratios')))
   s.enter_context(patch.object(ubpr,'report_cycles',return_value=[{'reportingcycleid':'154'}]))
   s.enter_context(patch.object(ubpr,'_post',return_value=raw))
   result=ubpr.fetch_ubpr_section('852218','Summary Ratios',all_periods=True)
  self.assertEqual(result['rows'][0]['2026-09-30'],10000)
 def test_missing_or_unknown_actual_source_type_rejected(self):
  from openbb_federal_reserve.utils import concepts
  for row in [{'conceptname':'MONEY','datatypeid':'999','09_30_2026':'10'},{'conceptname':'MONEY','09_30_2026':'10'}]:
   with self.subTest(row=row):
    with self.assertRaisesRegex(OpenBBError,'datatype'):
     concepts.report_concept_types([row])
if __name__=='__main__':unittest.main(verbosity=2)
