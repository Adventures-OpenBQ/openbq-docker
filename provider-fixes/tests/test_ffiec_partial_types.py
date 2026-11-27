"""Mount captured ffiec-live directory at /captures; use the installed fetcher helpers."""
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import json
import re
import unittest

from openbb_federal_reserve.utils import peer_group_report as peer
from openbb_core.app.model.abstract.error import OpenBBError


class PartialTypes(unittest.TestCase):
    def test_missing_reference_bank_code_cannot_silently_change_units(self):
        root = Path(__file__).parent / "fixtures" / "ffiec-live"
        bank = json.loads((root / "router-lines.json").read_text())
        raw = json.loads((root / "raw-summary-report-valid.json").read_text())
        # Represent a reference-bank page without the group's Average Total Assets line.
        bank = [row for row in bank if not any(
            "UBPRD659" in str(cell) for col, cell in row.items()
            if re.fullmatch(r"\d{2}_\d{2}_\d{4}", col)
        )]
        source = next(s["9/30/2026"] for _, code, s in raw["parsed"] if code == "UBPRD659")
        root_name = "openbb_federal_reserve.utils."
        with ExitStack() as stack:
            for name, val in {
                "peer_group_report._fetch_section_batch": raw,
                "cdr.fetch_taxonomy": b"<schema/>",
                "ubpr_report._section_id": ("502574","Summary Ratios"),
                "ubpr_report.report_cycles": [{"reportingcycleid":"154"}],
                "ubpr_report._post": bank,
                "mdrm.fetch_mdrm_dictionary": {},
                "mdrm.fetch_mdrm_definitions": {},
                "guide.fetch_guide_concepts": {},
            }.items():
                stack.enter_context(patch(root_name + name, return_value=val))
            stack.enter_context(patch(root_name + "cache.cached",side_effect=lambda k,t,p:p()))
            try:
                rows = peer.fetch_peer_group_section(1,"Summary Ratios",periods=1)["rows"]
            except OpenBBError as exc:
                self.assertRegex(str(exc), r"(?i)(datatype|scal|unit|concept)")
                return
        row = next(row for row in rows if "Average Total Assets" in row["label"])
        self.assertEqual(row["2026-09-30"], source*1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
