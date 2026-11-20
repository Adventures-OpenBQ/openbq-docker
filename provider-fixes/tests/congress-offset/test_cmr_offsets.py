# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""GovInfo page numbers must preserve Congress API record-offset semantics."""
import asyncio
import unittest
from unittest.mock import patch
from openbb_government_us.congress.utils import bulk

class MandatedReportOffsets(unittest.TestCase):
    def fetch(self, offset, size):
        seen=[]
        async def search(query, *, offset, pagesize):
            seen.append((offset,pagesize))
            records=[{'fieldMap':{'packageid':f'CMR-{i}'},'line1':f'Report {i}','line2':''} for i in range(7)]
            return {'resultSet':records[offset*pagesize:(offset+1)*pagesize]}
        with patch.object(bulk,'wssearch',search):
            rows=asyncio.run(bulk._fetch_cmr_wssearch(119,size,offset))
        return [r['package_id'] for r in rows],seen

    def test_non_page_aligned_offsets_preserve_exact_window(self):
        for offset,size in [(1,2),(3,3),(5,2),(0,2),(6,2),(9,2)]:
            with self.subTest(offset=offset,size=size):
                rows,_=self.fetch(offset,size)
                self.assertEqual(rows,[f'CMR-{i}' for i in range(7)][offset:offset+size])

    def test_aligned_offset_needs_only_one_page(self):
        rows,seen=self.fetch(2,2)
        self.assertEqual(rows,['CMR-2','CMR-3'])
        self.assertEqual(seen,[(1,2)])
