# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Exercise the real Compose JSON boundary without creating Docker resources."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/compose-run.py'
DIRECTORIES = 'com.openbq.regression.state-directories'


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose client is required')
class ComposeJsonBoundaryTests(unittest.TestCase):
    def setUp(self):
        probe = subprocess.run(['docker', 'compose', 'version'], capture_output=True)
        if probe.returncode:
            self.skipTest('Docker Compose plugin is required')
        spec = importlib.util.spec_from_file_location('compose_run_go', SCRIPT)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)

    def recipe(self, root):
        mount = {'type': 'bind', 'source': str(root / 'missing-state'),
                 'target': '/data', 'bind': {'create_host_path': True}}
        service = {'image': 'busybox:stable', 'profiles': ['live'],
                   'labels': {DIRECTORIES: '["/data"]'}, 'volumes': [mount]}
        path = root / 'compose.json'
        path.write_text(json.dumps({'services': {
            'api': {'image': 'busybox:stable'}, 'store': service,
        }}))
        return path

    def test_selected_profile_is_available_to_the_isolation_dependency_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, _ = self.runner.load_recipe([self.recipe(root)])
            self.assertIn('store', model['services'])
            self.assertFalse((root / 'missing-state').exists())

    def test_real_compose_json_preserves_directory_intent_and_uses_fresh_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.recipe(root)
            raw = subprocess.check_output([
                'docker', 'compose', '-f', str(path), '--profile', '*',
                'config', '--format', 'json', '--no-env-resolution',
            ], stderr=subprocess.PIPE)
            model = json.loads(raw)
            try:
                isolated = self.runner.prepare_model(model, ['store'], 'openbq-regression-go-boundary')
            except ValueError as error:
                self.fail('Compose directory intent did not survive isolation: ' + str(error))
            mount = isolated['services']['store']['volumes'][0]
            self.assertEqual(mount['type'], 'volume')
            self.assertFalse(mount.get('volume', {}).get('nocopy', False))
            self.assertFalse((root / 'missing-state').exists())
            self.assertNotIn('api', isolated['services'])

    def test_conflicting_extension_and_serializable_label_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = json.loads(self.recipe(root).read_text())
            model['services']['store']['x-openbq-regression-state-directories'] = ['/different']
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                self.runner.prepare_model(model, ['store'], 'openbq-regression-go-boundary')

    def test_explicit_false_create_directory_still_refuses_a_missing_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = json.loads(self.recipe(root).read_text())
            model['services']['store']['volumes'][0]['bind']['create_host_path'] = False
            with self.assertRaises(ValueError):
                self.runner.prepare_model(model, ['store'], 'openbq-regression-go-boundary')


if __name__ == '__main__':
    unittest.main()
