# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""A regression run must never inherit another installation's mutable state."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/compose-run.py'


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'the recipe regression launcher is missing')
        spec = importlib.util.spec_from_file_location('compose_run', SCRIPT)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.project = 'openbq-regression-test123'
        self.model = {
            'name': 'ordinary-install',
            'services': {'api': {
                'build': {'context': '.'}, 'image': 'ordinary-api:latest',
                'networks': {'private': None},
                'volumes': [{'type': 'volume', 'source': 'data', 'target': '/data',
                             'volume': {'nocopy': True}}],
            }},
            'volumes': {'data': {'name': 'ordinary-shared-data'}},
            'networks': {'private': {'name': 'ordinary-private', 'internal': True}},
        }

    def prepare(self, model=None, services=None, project=None):
        return self.runner.prepare_model(model or self.model, services or ['api'],
                                         project or self.project)

    def test_new_namespace_and_normal_volume_initialization(self):
        first = self.prepare()
        second = self.prepare(project='openbq-regression-other456')
        self.assertNotEqual(first['volumes']['data']['name'], second['volumes']['data']['name'])
        self.assertNotEqual(first['volumes']['data']['name'], 'ordinary-shared-data')
        self.assertFalse(first['services']['api']['volumes'][0]['volume'].get('nocopy', False))
        self.assertNotIn('name', first['networks']['private'])
        self.assertTrue(first['networks']['private']['internal'])
        self.assertEqual(first['services']['api']['image'], self.project + '-api:candidate')
        self.assertEqual(self.model['name'], 'ordinary-install')

    def test_readonly_configuration_is_preserved_but_writable_directory_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.model['services']['api']['volumes'] += [
                {'type': 'bind', 'source': tmp, 'target': '/state'},
                {'type': 'bind', 'source': tmp, 'target': '/config', 'read_only': True},
            ]
            actual = self.prepare()['services']['api']['volumes']
            self.assertEqual(actual[1]['type'], 'volume')
            self.assertNotEqual(actual[1]['source'], tmp)
            self.assertFalse(actual[1].get('read_only', False))
            self.assertEqual(actual[2], self.model['services']['api']['volumes'][2])

    def test_dependency_closure_includes_build_and_service_namespace_dependencies(self):
        self.model['services']['api']['depends_on'] = {'gateway': {'condition': 'service_started'}}
        self.model['services']['gateway'] = {'build': {'context': './gateway'}, 'network_mode': 'service:tunnel'}
        self.model['services']['tunnel'] = {'image': 'pinned-sidecar@sha256:' + 'a' * 64}
        self.model['services']['unrelated'] = {'image': 'unrelated:latest'}
        actual = self.prepare()
        self.assertEqual(set(actual['services']), {'api', 'gateway', 'tunnel'})
        self.assertEqual(actual['services']['gateway']['network_mode'], 'service:tunnel')

    def test_build_service_context_dependencies_are_included(self):
        self.model['services']['api']['build']['additional_contexts'] = {'base': 'service:base'}
        self.model['services']['base'] = {'build': {'context': './base'}}
        self.assertEqual(set(self.prepare()['services']), {'api', 'base'})

    def test_rejects_foreign_state_and_exposure(self):
        variants = []
        for key, value in [('network_mode', 'host'), ('network_mode', 'container:foreign'),
                           ('ports', [{'target': 80, 'published': '8080'}]),
                           ('volumes_from', ['foreign']), ('container_name', 'ordinary-api')]:
            m = copy.deepcopy(self.model); m['services']['api'][key] = value; variants.append(m)
        m = copy.deepcopy(self.model); m['volumes']['data']['external'] = True; variants.append(m)
        for model in variants:
            with self.subTest(model=model):
                with self.assertRaises(ValueError): self.prepare(model)

    def test_writable_file_bind_is_refused_without_touching_it(self):
        with tempfile.NamedTemporaryFile() as f:
            path = Path(f.name); path.write_text('untouched')
            self.model['services']['api']['volumes'] = [{'type': 'bind', 'source': str(path), 'target': '/credentials'}]
            with self.assertRaises(ValueError): self.prepare()
            self.assertEqual(path.read_text(), 'untouched')

    def test_missing_services_and_non_regression_project_are_refused(self):
        with self.assertRaises(ValueError): self.prepare(services=['missing'])
        with self.assertRaises(ValueError): self.prepare(project='ordinary-install')

    def test_managed_networks_volumes_and_services_have_ownership_labels(self):
        result = self.prepare()
        for kind in ['services', 'networks', 'volumes']:
            for config in result[kind].values():
                self.assertEqual(config['labels']['com.openbq.regression.project'], self.project)

    def test_archive_inside_an_unrelated_checkout_is_not_that_checkout_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            recipe = root / 'compose.json'; recipe.write_text('{"services":{}}')
            subprocess.run(['git', '-C', tmp, 'add', 'compose.json'], check=True)
            subprocess.run(['git', '-C', tmp, '-c', 'user.name=QA', '-c',
                            'user.email=qa@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            tracked = self.runner.source_identity([recipe])
            self.assertEqual(len(tracked['source_revision']), 40)
            archive = root / 'untracked-archive'; archive.mkdir()
            exported = archive / 'compose.json'; exported.write_text(recipe.read_text())
            identity = self.runner.source_identity([exported])
            self.assertIsNone(identity['source_revision'])
            self.assertEqual(identity['recipe_files'][0]['sha256'], tracked['recipe_files'][0]['sha256'])

    def test_existing_receipt_is_preserved_before_any_docker_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / 'receipt.json'; receipt.write_text('prior proof')
            with self.assertRaises(ValueError):
                self.runner.main(['--regression', '--plan', '--report', str(receipt)])
            self.assertEqual(receipt.read_text(), 'prior proof')


if __name__ == '__main__':
    unittest.main()
