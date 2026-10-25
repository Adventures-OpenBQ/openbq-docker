# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json,subprocess,tempfile,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[2]/'scripts/check-public.py'
class PublicCheck(unittest.TestCase):
 def check(self,root,history=False):
  return subprocess.run(['python3',str(SCRIPT),*(['--history'] if history else [])],cwd=root,capture_output=True,text=True)
 def repo(self,d):
  subprocess.run(['git','init','-q',d],check=True)
 def commit(self,d):
  subprocess.run(['git','add','.'],cwd=d,check=True)
  subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','fixture'],cwd=d,check=True)
 def test_named_tailnet_rejected_without_printing_value(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);host='.'.join(['app','private-demo','ts','net']);Path(d,'report.md').write_text('https://'+host)
   r=self.check(d);self.assertEqual(r.returncode,1);self.assertIn('report.md',r.stdout);self.assertNotIn(host,r.stdout+r.stderr)
 def test_filled_demo_credential_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);Path(d,'credentials.env.example').write_text('FRED_API_KEY='+'demo_secret_123')
   r=self.check(d);self.assertEqual(r.returncode,1)
 def test_empty_credential_lines_allow_following_comments(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);Path(d,'credentials.env.example').write_text('FRED_API_KEY=\n# Comment\nEIA_API_KEY=\n')
   r=self.check(d);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_filled_json_credential_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);Path(d,'credentials.example.json').write_text(json.dumps({'api'+'_key':'demo'+'_secret_123'}))
   r=self.check(d);self.assertEqual(r.returncode,1)
 def test_placeholder_allowed(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);Path(d,'README.md').write_text('https://'+'openbq.YOUR-TAILNET.'+'ts.net')
   r=self.check(d);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_deleted_historical_host_is_still_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   self.repo(d);Path(d,'report.md').write_text('https://'+'.'.join(['app','private-demo','ts','net']));self.commit(d)
   Path(d,'report.md').write_text('sanitized');self.commit(d)
   r=self.check(d,True);self.assertEqual(r.returncode,1);self.assertIn('history',r.stdout)
if __name__=='__main__':unittest.main()
