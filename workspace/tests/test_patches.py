# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PATCHES=sorted((ROOT/'patches').glob('*.patch'))
class PatchTests(unittest.TestCase):
 def test_every_patch_carries_the_upstream_notice(self):
  self.assertEqual(json.loads((ROOT/'source.json').read_text())['repository'],
                   'https://github.com/OpenBB-finance/workspace')
  for p in PATCHES:
   head=p.read_text().split('--- a/',1)[0]
   for notice in ['OpenBB Workspace','OpenBB Inc.','Apache-2.0']:
    self.assertIn(notice,head,p.name)
 def test_manual_packaging_and_both_distinct_004_patches_are_documented(self):
  manual={'001-pinned-build-and-bun.patch','002-local-state-exclusions.patch',
          '003-runtime-healthcheck.patch','004-system-dashboard.patch',
          '004-frozen-backend-build.patch'}
  automatic={'005-workspace-request-boundaries.patch','006-public-test-key-packaging.patch'}
  self.assertEqual({p.name for p in PATCHES},manual|automatic)
  for name in ['README.md','REPRODUCE.md']:
   commands=re.findall(r'^patch -p1 < ../patches/(\S+)$',(ROOT/name).read_text(),re.M)
   self.assertEqual(set(commands),manual,name)
   self.assertEqual(len(commands),len(manual),name)
 def test_automatic_security_and_fixture_patches_are_applied_once_without_manual_duplicates(self):
  assembly=(ROOT/'scripts/assemble.sh').read_text()
  for name in ['005-workspace-request-boundaries.patch','006-public-test-key-packaging.patch']:
   self.assertEqual(assembly.count(name),1,name)
   for doc in ['README.md','REPRODUCE.md']:
    text=(ROOT/doc).read_text()
    self.assertRegex(text,re.compile(r'patch\s*'+name[:3],re.I))
    self.assertNotIn(f'patch -p1 < ../patches/{name}',text)
 def test_the_system_dashboard_migration_follows_the_pinned_head(self):
  text=(ROOT/'patches/004-system-dashboard.patch').read_text()
  self.assertIn('+down_revision = "0d4a342f4c26"',text)
  self.assertIn('+SYSTEM_DASHBOARD_IDS = {"docks"}',text)
  self.assertEqual(re.findall(r'^\+@router\.(\w+)\("/sync/system/\{system_id\}"\)',text,re.M),['get','put','delete'])
if __name__=='__main__': unittest.main()
