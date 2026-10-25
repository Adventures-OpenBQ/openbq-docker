# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def config(*profiles):
 # Render the real compose file in a scratch copy with the example env files in place.
 with tempfile.TemporaryDirectory() as d:
  p=Path(d); shutil.copy(ROOT/'docker-compose.yml',p)
  (p/'workspace').mkdir()
  shutil.copy(ROOT/'workspace/runtime.env.example',p/'workspace/runtime.env')
  shutil.copy(ROOT/'workspace/ts.env.example',p/'workspace/ts.env')
  shutil.copy(ROOT/'ts.env.example',p/'ts.env')
  shutil.copy(ROOT/'credentials.demo.env',p)  # committed and required by openbq-api
  args=['docker','compose']+[a for pr in profiles for a in ('--profile',pr)]+['config','--format','json']
  r=subprocess.run(args,cwd=p,capture_output=True,text=True,check=True)
  return json.loads(r.stdout)
@unittest.skipUnless(shutil.which('docker'),'docker compose required')
class ComposeTests(unittest.TestCase):
 def test_workspace_is_opt_in(self):
  self.assertNotIn('workspace',config()['services'])
 def test_workspace_profile_runs_on_its_own_node_and_network(self):
  s=config('workspace')['services']
  self.assertEqual(s['workspace-tailscale']['hostname'],'openbq-workspace')
  self.assertEqual(s['workspace-tailscale']['environment']['TS_HOSTNAME'],'openbq-workspace')
  self.assertEqual(set(s['workspace']['networks']),{'workspace-internal'})
  self.assertNotIn('workspace-internal',s['openbq-api']['networks'])
  state=[v for v in s['workspace-tailscale']['volumes'] if v['target']=='/var/lib/tailscale'][0]
  self.assertTrue(state['source'].endswith('/workspace/ts-state'))
 def test_workspace_keeps_the_existing_data_volume(self):
  c=config('workspace')
  self.assertEqual(c['volumes']['workspace-data']['name'],'openbq-episode2_workspace-data')
  self.assertEqual(c['networks']['workspace-internal']['driver_opts']['com.docker.network.driver.mtu'],'1500')
if __name__=='__main__': unittest.main()
