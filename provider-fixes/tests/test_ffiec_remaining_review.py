"""Offline integration-edge checks for the remaining UBPR portfolio."""
from contextlib import ExitStack
from unittest import TestCase, main
from unittest.mock import patch
from zipfile import BadZipFile

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_federal_reserve.models import peer_group_bank as bank
from openbb_federal_reserve.utils import custom_peer_group as custom
from openbb_federal_reserve.utils import executive_summary_report as esr
from openbb_federal_reserve.utils import ubpr_report as ubpr

ROOT = "openbb_federal_reserve.utils."
CYCLE = {"reportingcycleid": "154", "enddateformatted": "09/30/2026"}


def wired():
    stack = ExitStack()
    for name in ("mdrm.fetch_mdrm_dictionary", "mdrm.fetch_mdrm_definitions", "guide.fetch_guide_concepts"):
        stack.enter_context(patch(ROOT + name, return_value={}))
    stack.enter_context(patch(ROOT+"cache.cached",side_effect=lambda key,ttl,producer:producer()))
    return stack


class Review(TestCase):
    def test_esr_one_empty_subsection_preserves_others(self):
        with wired() as s:
            s.enter_context(patch(ROOT+"cdr.fetch_taxonomy",side_effect=BadZipFile()))
            s.enter_context(patch.object(esr,"report_cycles",return_value=[CYCLE]))
            s.enter_context(patch.object(esr,"report_sections",return_value=[{"sectionid":"A"},{"sectionid":"B"}]))
            good = [{"linecaption":"Assets","conceptname":"MONEY","datatypeid":"9","09_30_2026":"10"}]
            s.enter_context(patch.object(esr,"_post",side_effect=lambda _,args: [] if args["SectionID"]=="A" else good))
            rows = esr.fetch_executive_summary("852218")
            self.assertEqual(rows[0]["2026-09-30"], 10000.)

    def test_peer_bank_uses_valid_taxonomy_for_missing_row_type(self):
        with wired() as s:
            s.enter_context(patch(ROOT+"cdr.fetch_taxonomy",return_value=b"valid"))
            s.enter_context(patch(ROOT+"cdr.parse_taxonomy",return_value=[{"mdrm":"MONEY","data_type":"Monetary"}]))
            s.enter_context(patch.object(bank,"_page_id",return_value=("1","Summary Ratios")))
            s.enter_context(patch.object(bank,"_peer_group_name",return_value=("1","peers")))
            s.enter_context(patch.object(bank,"_peer_group_banks",return_value=[{"rssd":"852218","name":"Bank"}]))
            s.enter_context(patch.object(ubpr,"report_cycles",return_value=[CYCLE]))
            raw=[{"conceptname":"MONEY","linecaption":"Assets","09_852218":"10"}]
            s.enter_context(patch.object(ubpr,"_post",side_effect=lambda request,args: [{"sectionid":"1"}] if request=="MBReportPageSections" else raw))
            rows = bank.fetch_peer_group_bank_report("852218","Summary Ratios")["rows"]
            self.assertEqual(rows[0]["Bank (852218)"], 10000.)

    def test_legacy_custom_peer_history_does_not_bypass_revalidation(self):
        # The predecessor permits different concepts at identical row positions.
        # Its fully enriched result lives under this key for the quarter.
        from openbb_federal_reserve.utils import ubpr_report
        with wired() as s:
            cycles = [{"reportingcycleid":str(154-i),"enddateformatted":f"09/30/{2026-i}"} for i in range(6)]
            s.enter_context(patch.object(ubpr_report,"report_cycles",return_value=cycles))
            legacy_key = ("cpg_lines","451965","480228,852218",custom._section_index("Summary Ratios"),"154,153,152,151,150,149",True)
            legacy_rows = [{"label":"assets","is_header":False,"2026-09-30 Bank":10000.,"2021-09-30 Bank":1250.}]
            s.enter_context(patch(ROOT+"cache.cached",side_effect=lambda key,ttl,producer: legacy_rows if key==legacy_key else producer()))
            s.enter_context(patch(ROOT+"cdr._get_session",side_effect=OpenBBError("new loader invoked")))
            with self.assertRaisesRegex(OpenBBError,"new loader invoked"):
                custom.fetch_custom_peer_group("451965","480228,852218",all_periods=True)

if __name__ == "__main__":
    main(verbosity=2)
