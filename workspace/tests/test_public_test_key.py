# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Remove only the reviewed non-runtime TLS fixture before the runtime COPY."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/strip_public_test_key.py'
SYNTHETIC = b'synthetic public test fixture, never a credential\n'

class PublicTestKey(unittest.TestCase):
    def fixture(self, root, version='6.5.8'):
        site = root / 'site-packages'
        target = site / 'tornado/test/test.key'
        target.parent.mkdir(parents=True)
        target.write_bytes(SYNTHETIC)
        metadata = site / f'tornado-{version}.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text(f'Name: tornado\nVersion: {version}\n')
        (metadata / 'RECORD').write_bytes(b'original distribution record\n')
        (site / 'tornado/web.py').write_bytes(b'public runtime module\n')
        manifest = root / 'public-test-fixture-removals.json'
        return site, target, metadata, manifest

    def guard(self):
        self.assertTrue(SCRIPT.is_file(), 'Build-time exact fixture guard is not implemented')
        spec = importlib.util.spec_from_file_location('test_key_guard', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def remove(self, site, manifest, **over):
        params = {'expected_sha256': hashlib.sha256(SYNTHETIC).hexdigest(), 'expected_size': len(SYNTHETIC)}
        params.update(over)
        return self.guard().strip_test_key(site, manifest, **params)

    def test_exact_fixture_removed_other_bytes_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, metadata, report = self.fixture(Path(temp))
            before = {str(p.relative_to(site)): p.read_bytes() for p in site.rglob('*') if p.is_file() and p != key}
            self.remove(site, report)
            self.assertFalse(key.exists())
            self.assertEqual({str(p.relative_to(site)): p.read_bytes() for p in site.rglob('*') if p.is_file()}, before)
            receipt = json.loads(report.read_text())
            self.assertEqual(receipt['package'], 'tornado')
            self.assertEqual(receipt['version'], '6.5.8')
            self.assertEqual(receipt['removed']['path'], 'tornado/test/test.key')
            self.assertEqual(receipt['preserved_files'], 3)
            self.assertNotIn(temp, report.read_text())

    def test_mismatched_hash_or_length_preserves_key_and_no_report(self):
        for over in [{'expected_sha256': '0' * 64}, {'expected_size': 1}]:
            with self.subTest(over=over), tempfile.TemporaryDirectory() as temp:
                site, key, _, report = self.fixture(Path(temp))
                with self.assertRaisesRegex(ValueError, 'fixture bytes'):
                    self.remove(site, report, **over)
                self.assertEqual(key.read_bytes(), SYNTHETIC)
                self.assertFalse(report.exists())

    def test_wrong_package_version_preserves_key(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, _, report = self.fixture(Path(temp), '6.5.9')
            with self.assertRaisesRegex(ValueError, 'distribution'):
                self.remove(site, report)
            self.assertEqual(key.read_bytes(), SYNTHETIC)
            self.assertFalse(report.exists())

    def test_symlink_fixture_and_symlink_parent_are_refused(self):
        for parent in (False, True):
            with self.subTest(parent=parent), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                site, key, _, report = self.fixture(root)
                if parent:
                    key.parent.rename(root / 'outside')
                    key.parent.symlink_to(root / 'outside', target_is_directory=True)
                else:
                    key.rename(root / 'outside')
                    key.symlink_to(root / 'outside')
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    self.remove(site, report)
                self.assertEqual(key.read_bytes(), SYNTHETIC)
                self.assertFalse(report.exists())

    def test_missing_unaccounted_fixture_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, _, report = self.fixture(Path(temp))
            key.unlink()
            with self.assertRaises(FileNotFoundError):
                self.remove(site, report)
            self.assertFalse(report.exists())

    def test_existing_report_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, _, report = self.fixture(Path(temp))
            report.write_bytes(b'preserve existing receipt\n')
            with self.assertRaises(FileExistsError):
                self.remove(site, report)
            self.assertEqual(key.read_bytes(), SYNTHETIC)
            self.assertEqual(report.read_bytes(), b'preserve existing receipt\n')

    def test_report_write_failure_does_not_remove_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, _, report = self.fixture(Path(temp))
            report = report.parent / 'missing-directory' / report.name
            with self.assertRaises(FileNotFoundError):
                self.remove(site, report)
            self.assertEqual(key.read_bytes(), SYNTHETIC)

    def test_remove_failure_cleans_only_its_new_report(self):
        with tempfile.TemporaryDirectory() as temp:
            site, key, _, report = self.fixture(Path(temp))
            unlink = Path.unlink
            def blocked(path, *args, **kwargs):
                if path == key:
                    raise OSError('synthetic unlink refusal')
                return unlink(path, *args, **kwargs)
            with patch.object(Path, 'unlink', blocked), self.assertRaisesRegex(OSError, 'unlink refusal'):
                self.remove(site, report)
            self.assertEqual(key.read_bytes(), SYNTHETIC)
            self.assertFalse(report.exists())

if __name__ == '__main__':
    unittest.main()
