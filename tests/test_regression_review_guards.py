# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Reproduce the launcher review's state, output and concurrency boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/compose-run.py'


class ReviewGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('reviewed_launcher', SCRIPT)
        self.r = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.r)
        self.project = 'openbq-regression-review123'

    def model(self):
        return {'services': {'app': {'build': {'context': '.'}}}, 'volumes': {}}

    def test_interpolated_readonly_cannot_bypass_writable_file_refusal(self):
        with tempfile.NamedTemporaryFile() as f:
            m = self.model(); m['services']['app']['volumes'] = [
                {'type': 'bind', 'source': f.name, 'target': '/private-file', 'read_only': '${QA_READONLY}'}]
            with self.assertRaises(ValueError): self.r.prepare_model(m, ['app'], self.project)

    def test_unresolved_paths_cannot_be_silently_anchored_then_reinterpreted(self):
        m = self.model(); m['services']['app']['volumes'] = [
            {'type': 'bind', 'source': '/wrong-prefix/${QA_ABSOLUTE_PATH}', 'target': '/config', 'read_only': True}]
        with self.assertRaises(ValueError): self.r.prepare_model(m, ['app'], self.project)

    def test_foreign_namespaces_and_scaling_are_refused_before_start(self):
        for key, value in [('pid', 'host'), ('ipc', 'host'), ('uts', 'host'),
                           ('pid', 'container:foreign'), ('ipc', 'container:foreign'),
                           ('userns_mode', 'host'), ('scale', 2), ('deploy', {'replicas': 2})]:
            with self.subTest(key=key, value=value):
                m = self.model(); m['services']['app'][key] = value
                with self.assertRaises(ValueError): self.r.prepare_model(m, ['app'], self.project)

    def test_build_cannot_retag_or_export_to_ordinary_deployment_outputs(self):
        m = self.model(); m['services']['app']['build']['tags'] = ['ordinary-app:latest']
        actual = self.r.prepare_model(m, ['app'], self.project)
        self.assertFalse(actual['services']['app']['build'].get('tags'))
        for key in ['outputs', 'cache_to']:
            m = self.model(); m['services']['app']['build'][key] = ['type=registry,ref=ordinary-app:latest']
            with self.assertRaises(ValueError): self.r.prepare_model(m, ['app'], self.project)

    def test_generated_volume_keys_are_disjoint_from_declared_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.model(); m['volumes'] = {'state-app-0': {}}
            m['services']['app']['volumes'] = [
                {'type': 'bind', 'source': tmp, 'target': '/first'},
                {'type': 'volume', 'source': 'state-app-0', 'target': '/second'}]
            mounts = self.r.prepare_model(m, ['app'], self.project)['services']['app']['volumes']
            self.assertNotEqual(mounts[0]['source'], mounts[1]['source'])

    def test_build_secret_declaration_is_retained(self):
        m = self.model(); m['services']['app']['build']['secrets'] = [{'source': 'build-input'}]
        m['secrets'] = {'build-input': {'environment': 'QA_BUILD_INPUT'}}
        self.assertEqual(self.r.prepare_model(m, ['app'], self.project)['secrets'], m['secrets'])

    def test_build_only_services_do_not_become_runtime_targets(self):
        m = self.model(); m['services']['app']['build']['additional_contexts'] = {'base': 'service:base'}
        m['services']['app']['depends_on'] = {'init': {'condition': 'service_completed_successfully'}}
        m['services']['base'] = {'build': {'context': './base'}}
        m['services']['init'] = {'image': 'qualified-init:qa'}
        runtime, completed = self.r.runtime_services(m, ['app'])
        self.assertEqual(runtime, {'app', 'init'}); self.assertEqual(completed, {'init'})

    def test_prebuilt_tag_is_replaced_with_verified_immutable_identity(self):
        m = {'services': {'app': {'image': 'mutable:qa'}}}; image = 'sha256:' + 'a' * 64
        bound = self.r.pin_images(m, ['app'], {'app': image}, lambda name: image)
        self.assertEqual(m['services']['app']['image'], image)
        self.assertEqual(bound, {'app': image})

    def test_model_string_values_are_not_persisted_in_clear(self):
        value = 'SYNTHETIC_' + 'PRIVATE_VALUE_FOR_TEST'
        m = {'services': {'app': {'image': 'safe:qa', 'environment': {'QA_VALUE': value},
                                 'command': ['sh', '-c', 'echo $CONTAINER_VAR']}}}
        rendered, environment = self.r.cloaked_model(m)
        self.assertNotIn(value, json.dumps(rendered))
        self.assertIn(value, environment.values())
        self.assertIn('echo $CONTAINER_VAR', environment.values())

    def test_child_diagnostics_do_not_reach_launcher_console(self):
        secret = 'SYNTHETIC_' + 'DIAGNOSTIC_VALUE'
        code = ("import runpy,sys; m=runpy.run_path(sys.argv[1]);"
                "m['run_command']([sys.executable,'-c','import sys;print(sys.argv[1],file=sys.stderr)',sys.argv[2]])")
        child = subprocess.run([sys.executable, '-c', code, str(SCRIPT), secret], capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertNotIn(secret, child.stdout + child.stderr)

    def test_atomic_receipt_does_not_clobber_a_concurrent_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'receipt.json'; path.write_text('concurrent proof')
            with self.assertRaises((ValueError, FileExistsError)):
                self.r.publish_report({'status': 'pass'}, path)
            self.assertEqual(path.read_text(), 'concurrent proof')
            fresh = Path(tmp) / 'fresh.json'; self.r.publish_report({'status': 'pass'}, fresh)
            self.assertEqual(json.loads(fresh.read_text())['status'], 'pass')
            self.assertEqual(stat.S_IMODE(fresh.stat().st_mode), 0o600)

    def test_failed_inventory_still_returns_unknown_cleanup_receipt(self):
        with patch.object(self.r, 'run_command') as run, patch.object(self.r, 'remaining_resources', side_effect=OSError):
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            result = self.r.cleanup_project(['docker', 'compose'], self.project, Path.cwd(), {})
        self.assertFalse(result['pass']); self.assertEqual(result['verification'], 'unknown')

    def test_list_environment_and_labels_are_normalized_safely(self):
        m = self.model(); m['services']['app'].update(labels=['fixture=yes'], environment=['TS_HOSTNAME'])
        service = self.r.prepare_model(m, ['app'], self.project)['services']['app']
        self.assertEqual(service['labels']['fixture'], 'yes')
        self.assertEqual(service['environment']['TS_HOSTNAME'], self.project + '-app')

    def test_explicit_recipe_uses_its_own_directory_and_resolves_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); recipe = root / 'recipe'; recipe.mkdir()
            config = recipe / 'settings.json'; config.write_text('{}')
            m = self.model(); m['services']['app']['volumes'] = [
                {'type': 'bind', 'source': '${QA_CONFIG_ABSOLUTE}', 'target': '/config', 'read_only': True}]
            file = recipe / 'compose.json'; file.write_text(json.dumps(m))
            with patch.dict(os.environ, {'QA_CONFIG_ABSOLUTE': str(config)}):
                loaded, base = self.r.load_recipe([str(file)])
            self.assertEqual(base, recipe.resolve())
            self.assertEqual(Path(loaded['services']['app']['build']['context']).resolve(), recipe.resolve())
            self.assertEqual(Path(loaded['services']['app']['volumes'][0]['source']).resolve(), config.resolve())

    def test_private_network_cannot_be_replaced_with_host_driver(self):
        m = self.model(); m['services']['app']['networks'] = {'unsafe': None}
        m['networks'] = {'unsafe': {'driver': 'host'}}
        with self.assertRaises(ValueError): self.r.prepare_model(m, ['app'], self.project)

    def test_loaded_model_decodes_compose_literal_dollar_escaping_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = 'SYNTHETIC_' + '$$LITERAL'
            m = self.model(); m['services']['app']['environment'] = {'QA_VALUE': value}
            m['services']['app']['command'] = ['sh', '-c', 'echo $$CONTAINER_VAR']
            file = Path(tmp) / 'compose.json'; file.write_text(json.dumps(m))
            loaded, _ = self.r.load_recipe([str(file)])
            self.assertEqual(loaded['services']['app']['environment']['QA_VALUE'], value.replace('$$', '$'))
            self.assertEqual(loaded['services']['app']['command'], ['sh', '-c', 'echo $CONTAINER_VAR'])


if __name__ == '__main__': unittest.main()
