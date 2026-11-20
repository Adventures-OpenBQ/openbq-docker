import unittest
from contextlib import ExitStack
from unittest.mock import patch
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_federal_reserve.utils import peer_group_distribution as distribution,state_average_report as state,concepts
ROOT='openbb_federal_reserve.utils.'
class NumericCoverage(unittest.TestCase):
    def test_distribution_numeric_code_must_be_resolved(self):
        with patch(ROOT+'guide.fetch_guide_concepts',return_value={}):
            with self.assertRaisesRegex(OpenBBError,'UBPRD659'):
                distribution._enrich([{'label':'Average Total Assets','is_header':False,'50TH':10.0}],{'Average Total Assets':'UBPRD659'}, {})
    def test_bank_count_memo_resolves_source_concept(self):
        self.assertEqual(distribution._row_concept({'label':'Number of Banks in Peer Group',distribution.PEER_GROUP_COLUMN:29.0},{}),'UBPAE877')
        with patch(ROOT+'guide.fetch_guide_concepts',return_value={}):
            rows=distribution._enrich([{'label':'Number of Banks in Peer Group',distribution.PEER_GROUP_COLUMN:29.0}],{}, {'UBPAE877':{'monetary':False}})
        self.assertEqual(rows[0][distribution.PEER_GROUP_COLUMN],29.0)
    def test_known_distribution_units_retained(self):
        rows=[{'label':'assets','50TH':10.0},{'label':'ratio','50TH':1.25},{'label':'count','50TH':29.0}]
        mapping={'assets':'A','ratio':'R','count':'C'}
        index={'A':{'monetary':True},'R':{'monetary':False},'C':{'monetary':False}}
        with patch(ROOT+'guide.fetch_guide_concepts',return_value={}):out=distribution._enrich(rows,mapping,index)
        self.assertEqual([x['50TH'] for x in out],[10000.0,1.25,29.0])
    def test_state_all_periods_missing_type_cannot_guess(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(state,'report_sections',return_value=[{'pagetitle':'Summary Ratios'}]))
            stack.enter_context(patch.object(state,'peer_group_id',return_value=4))
            stack.enter_context(patch(ROOT+'ubpr_report.report_cycles',return_value=[{'reportingcycleid':'154'},{'reportingcycleid':'10'}]))
            stack.enter_context(patch(ROOT+'concepts.concept_index',return_value={'R':{'monetary':False}}))
            stack.enter_context(patch(ROOT+'guide.fetch_guide_concepts',return_value={}))
            def cached(key,ttl,producer):return {'dates':['2026-09-30'],'rows':[{'label':'assets','values':['10'],'concept':'UBPRD659'}]}
            stack.enter_context(patch(ROOT+'cache.cached',side_effect=cached))
            with self.assertRaisesRegex(OpenBBError,'UBPRD659'):
                state.fetch_state_average_section('SD',all_periods=True)
    def test_historical_type_conflict_fails_instead_of_collapsing_units(self):
        responses=[[{'01_01_2001':"1;SAME;9;0;''"}],[{'01_01_2002':"1;SAME;96;0;''"}]]
        with patch(ROOT+'ubpr_report._section_id',return_value=('layout','Summary Ratios')),patch(ROOT+'ubpr_report._post',side_effect=responses):
            with self.assertRaisesRegex(OpenBBError,'Conflicting.*SAME'):
                concepts._report_concept_types('Summary Ratios','1,2,3,4,5,6')
    def test_types_follow_requested_historical_periods_in_bounded_batches(self):
        ids=','.join(str(n) for n in range(10,17));calls=[]
        def post(requestor,criteria):
            calls.append(criteria)
            return [{'01_01_2001':"10;ASSET;9;0;'', 1.25;RATIO;96;2;''"}]
        with patch(ROOT+'ubpr_report._section_id',return_value=('oldlayout','Capital Analysis-a')),patch(ROOT+'ubpr_report._post',side_effect=post),patch(ROOT+'ubpr_report.report_cycles',side_effect=AssertionError('must not substitute newest cycles')):
            result=concepts._report_concept_types('Capital Analysis-a',ids)
        self.assertEqual(result,{'ASSET':'Monetary','RATIO':'Ratio'})
        self.assertEqual([c['ReportingCycleIdList'] for c in calls],['10,11,12,13,14','15,16'])
        self.assertTrue(all(c['ScheduleID']=='oldlayout' for c in calls))
if __name__=='__main__':unittest.main(verbosity=2)
