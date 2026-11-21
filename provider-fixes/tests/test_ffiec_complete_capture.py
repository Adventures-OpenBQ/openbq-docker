from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import json,unittest
from openbb_federal_reserve.utils import peer_group_report as peer
class CompleteCapture(unittest.TestCase):
    def test_complete_source_types_preserve_money_ratio_and_bank_count(self):
        root=Path(__file__).parent / "fixtures" / "ffiec-live";bank=json.loads((root/'router-lines.json').read_text());raw=json.loads((root/'raw-summary-report-valid.json').read_text());prefix='openbb_federal_reserve.utils.'
        with ExitStack() as stack:
            for name,value in {'peer_group_report._fetch_section_batch':raw,'cdr.fetch_taxonomy':b'<schema/>','ubpr_report._section_id':('502574','Summary Ratios'),'ubpr_report.report_cycles':[{'reportingcycleid':'154'}],'ubpr_report._post':bank,'mdrm.fetch_mdrm_dictionary':{},'mdrm.fetch_mdrm_definitions':{},'guide.fetch_guide_concepts':{}}.items():stack.enter_context(patch(prefix+name,return_value=value))
            stack.enter_context(patch(prefix+'cache.cached',side_effect=lambda key,ttl,producer:producer()))
            rows=peer.fetch_peer_group_section(4,'Summary Ratios',periods=1)['rows']
        for code,label,factor in [('UBPRD659','Average Total Assets',1000),('UBPRE001','Interest Income (TE)',1),('UBPAE877','Number of banks in Peer Group',1)]:
            source=next(series['9/30/2026'] for _,c,series in raw['parsed'] if c==code)
            result=next(row['2026-09-30'] for row in rows if row['label'].lstrip('>\xa0 ')==label)
            self.assertEqual(result,source*factor)
