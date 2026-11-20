# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Cold FFIEC defaults preserve five periods without serial download latency."""
import threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import patch

class ColdPeriods(unittest.TestCase):
 def test_recent_periods_fetch_concurrently_and_preserve_report_order(self):
  from openbb_federal_reserve.models.call_report_router import FederalReserveCallReportSectionedFetcher as F
  import openbb_federal_reserve.utils.cdr as cdr
  active=peak=0;lock=threading.Lock();dates=['09/30/2026','06/30/2026','03/31/2026','12/31/2025','09/30/2025']
  def fetch(product,period=None,fmt='xbrl'):
   nonlocal active,peak
   with lock:active+=1;peak=max(peak,active)
   time.sleep(.03)
   with lock:active-=1
   return b'PK'+(period or dates[0]).encode()
  def parse(content,rssd):
   date=content[2:].decode();mm,dd,yy=date.split('/');iso=f'{yy}-{mm}-{dd}'
   return {'form_type':'031','name':'Test bank','items':[{'mdrm':'RCFD2170','period':iso,'value':'10'}]}
  with ExitStack() as stack:
   for module,name,value in [(cdr,'fetch_bulk',fetch),(cdr,'bulk_rssids',lambda _:['451965']),(cdr,'list_periods',lambda _:[{'date':d} for d in dates]),(cdr,'parse_xbrl_instance',parse),(cdr,'presentation_map',lambda *a:{'RCFD2170':{'section':'Schedule RC - Balance Sheet','label':'Assets','order':1,'level':1}})]:stack.enter_context(patch.object(module,name,side_effect=value))
   stack.enter_context(patch('openbb_federal_reserve.utils.ticker.lead_subsidiary_bank',return_value='451965'))
   stack.enter_context(patch('openbb_federal_reserve.utils.concepts.concept_index',return_value={'RCFD2170':{'is_text':False,'name':'Assets'}}))
   result=F.extract_data(F.transform_query({'rssd_id':'451965','all_periods':False}),None)
  self.assertEqual(result[0]['_periods'],['2026-09-30','2026-06-30','2026-03-31','2025-12-31','2025-09-30'])
  self.assertEqual(len(result),2);self.assertEqual(result[1]['2026-09-30'],10)
  self.assertGreater(peak,1);self.assertLessEqual(peak,2)
 def test_cdr_sessions_are_distinct_between_postback_threads(self):
  import openbb_federal_reserve.utils.cdr as cdr
  barrier=threading.Barrier(2)
  def key(_):barrier.wait();return cdr._get_session()
  cdr._get_session()  # Prime the old shared session before concurrent callers.
  with ThreadPoolExecutor(max_workers=2) as pool:keys=list(pool.map(key,[1,2]))
  self.assertIsNot(keys[0],keys[1])
  for session in keys:session.close()
 def test_custom_peer_registration_keeps_the_render_session(self):
  from unittest.mock import Mock
  import openbb_federal_reserve.utils.cdr as cdr
  from openbb_federal_reserve.utils.custom_peer_group import _set_peer_group
  made=[]
  def factory(**kwargs):
   session=Mock();session.post.return_value.json.return_value=[];made.append(session);return session
  with patch.object(cdr,'_sessions',threading.local(),create=True),patch.object(cdr,'Session',side_effect=factory):
   render_session=cdr._get_session()
   _set_peer_group(render_session,'451965,480228,852218','154')
   self.assertIs(cdr._get_session(),render_session)
  self.assertEqual(len(made),1)
  self.assertEqual(render_session.post.call_count,2)
  self.assertIn('SetSessionData',render_session.post.call_args.kwargs['data'])
 def test_federal_reserve_cold_budget_is_bounded_and_overrideable(self):
  from openbb_core.app import command_runner as m
  self.assertEqual(m._read_deadlines({}).get('federal_reserve'),150)
  self.assertEqual(m._read_deadlines({'OPENBQ_COMMAND_TIMEOUT_FEDERAL_RESERVE':'90'})['federal_reserve'],90)
