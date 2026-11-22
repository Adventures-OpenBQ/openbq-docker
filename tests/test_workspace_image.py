"""Render the real optional profile without touching Docker state or credential files."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED = 'ghcr.io/adventures-openbq/openbq-docker@sha256:218f6c7098c43abd929ad7d511065ad4e48cade8ed221e13aa46c931a7f53443'

@unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI required for recipe rendering')
class WorkspaceImage(unittest.TestCase):
    def image(self, override=None):
        env = dict(os.environ)
        env.pop('OPENBQ_WORKSPACE_IMAGE', None)
        env['COMPOSE_DISABLE_ENV_FILE'] = '1'
        if override is not None:
            env['OPENBQ_WORKSPACE_IMAGE'] = override
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(['docker', 'compose', '--project-directory', folder,
                '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'docker-compose.v3.yml'),
                '--profile', 'workspace', 'config', '--no-env-resolution', '--format', 'json'],
                cwd=folder, env=env, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['services']['workspace']

    def test_default_is_the_qualified_amd64_digest(self):
        service = self.image()
        self.assertEqual(service['image'], QUALIFIED)
        self.assertEqual(service['platform'], 'linux/amd64')

    def test_reader_can_use_their_source_build(self):
        self.assertEqual(self.image('openbq-workspace-local:reader-build')['image'], 'openbq-workspace-local:reader-build')

if __name__ == '__main__':
    unittest.main()
