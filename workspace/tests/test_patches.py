# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PATCHES=sorted((ROOT/'patches').glob('*.patch'))
class PatchTests(unittest.TestCase):
 def test_every_patch_carries_the_upstream_notice_and_is_in_the_readme(self):
  readme=(ROOT/'README.md').read_text()
  for p in PATCHES:
   head=p.read_text().splitlines()[:4]
   self.assertIn('OpenBB-finance/workspace',head[0],p.name);self.assertIn('Apache-2.0',head[3],p.name)
   self.assertIn(f'patch -p1 < ../patches/{p.name}',readme,p.name)
 def test_the_system_dashboard_migration_follows_the_pinned_head(self):
  text=(ROOT/'patches/004-system-dashboard.patch').read_text()
  self.assertIn('+down_revision = "0d4a342f4c26"',text)
  self.assertIn('+SYSTEM_DASHBOARD_IDS = {"docks"}',text)
  self.assertEqual(re.findall(r'^\+@router\.(\w+)\("/sync/system/\{system_id\}"\)',text,re.M),['get','put','delete'])
if __name__=='__main__': unittest.main()
