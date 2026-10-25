# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import subprocess, tempfile, unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/assemble.sh'
class AssemblyTests(unittest.TestCase):
 def test_wrong_commit_preserves_checkout(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); subprocess.run(['git','init','-q',d],check=True)
   marker=p/'keep.txt'; marker.write_text('preserve')
   r=subprocess.run(['bash',str(SCRIPT),d],capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0)
   self.assertIn('Source commit mismatch',r.stderr)
   self.assertEqual(marker.read_text(),'preserve')
if __name__=='__main__': unittest.main()
