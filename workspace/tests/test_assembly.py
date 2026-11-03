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
class PatchProvenanceTests(unittest.TestCase):
 def test_modified_assembled_file_is_refused_before_any_patch(self):
  import hashlib,json,shutil
  workspace=SCRIPT.parent.parent
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'scripts').mkdir();(root/'patches').mkdir();context=root/'build-context';context.mkdir()
   shutil.copyfile(workspace/'scripts/apply-patches.sh',root/'scripts/apply-patches.sh')
   (context/'source.py').write_text('original')
   digest=hashlib.sha256(b'original').hexdigest()
   record={'upstream':'be00e95019a55d57af146919ee46b7e1a4859226','files':{'source.py':digest}}
   (context/'.workspace-source.json').write_text(json.dumps(record))
   (root/'source.json').write_text(json.dumps({'commit':record['upstream'],'lock_sha256':{}}))
   for n in range(1,6):(root/'patches'/f'{n:03d}-fixture.patch').write_text('')
   (context/'source.py').write_text('modified')
   result=subprocess.run(['bash',str(root/'scripts/apply-patches.sh')],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0)
   self.assertIn('Assembled source checksum mismatch',result.stderr)
   self.assertFalse((context/'.workspace-patches.json').exists())

if __name__=='__main__': unittest.main()
