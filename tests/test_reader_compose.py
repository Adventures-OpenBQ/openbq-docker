"""Reader rehearsals must select demo credentials and their own Workspace store."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ReaderCompose(unittest.TestCase):
    def config(self, project, demo=True):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'workspace').mkdir()
            for name in ('docker-compose.yml', 'docker-compose.demo.yml', 'credentials.demo.env'):
                shutil.copyfile(ROOT / name, root / name)
            for name in ('ts.env', 'workspace/ts.env', 'credentials.env'):
                (root / name).write_text('')
            shutil.copyfile(ROOT / 'workspace/runtime.env.example', root / 'workspace/runtime.env')
            cmd = ['docker', 'compose', '-p', project, '-f', str(root / 'docker-compose.yml')]
            if demo:
                cmd += ['-f', str(root / 'docker-compose.demo.yml')]
            cmd += ['--profile', 'workspace', 'config', '--format', 'json']
            return json.loads(subprocess.check_output(cmd, cwd=root))

    def test_reader_image_and_credentials(self):
        services = self.config('reader-v2-a')['services']
        api = services['openbq-api']
        self.assertEqual(api['image'], 'openbq-local:2.0.0-reader')
        self.assertEqual(services['workspace']['image'], 'openbq-workspace-local:2.0.0-reader')
        self.assertEqual(api['environment'], {'EIA_API_KEY': 'DEMO_KEY', 'CONGRESS_GOV_API_KEY': 'DEMO_KEY'})

    def test_reader_workspace_stores_do_not_collide(self):
        a = self.config('reader-v2-a')['volumes']['workspace-data']['name']
        b = self.config('reader-v2-b')['volumes']['workspace-data']['name']
        self.assertNotEqual(a, 'openbq-episode2_workspace-data')
        self.assertNotEqual(a, b)

    def test_default_workspace_keeps_migration_store(self):
        self.assertEqual(self.config('reader-v2-base', demo=False)['volumes']['workspace-data']['name'], 'openbq-episode2_workspace-data')

if __name__ == '__main__':
    unittest.main()
