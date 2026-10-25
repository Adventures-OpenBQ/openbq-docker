# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""scripts/check-public.py address rules (stdlib unittest; run: python3 -m unittest discover tests).

Fixtures are split so this file does not trip the scanner it tests.
"""
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-public.py"
RESOLVER = "100.100." "100.100"
FLAGGED = ["100.100.100" ".10", "100.100.100" ".101", "100.101" ".2.3",
           "fd7a:115c:a1e0:" "ab12:4843:cd96:625b:1234", "fd7a:115c:a1e0:" ":1"]


def scan(text):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        Path(d, "note.md").write_text(text + "\n")
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=d, capture_output=True, text=True).returncode


class Addresses(unittest.TestCase):
    def test_magicdns_resolver_is_exempt(self):
        self.assertEqual(scan("nameserver " + RESOLVER), 0)

    def test_other_tailnet_addresses_are_flagged(self):
        for addr in FLAGGED:
            with self.subTest(addr=addr):
                self.assertEqual(scan("peer " + addr), 1)

    def test_the_bare_ula_prefix_is_not_an_address(self):
        self.assertEqual(scan("fd7a:115c:a1e0::/48"), 0)


class DemoKeys(unittest.TestCase):
    def test_a_public_demo_key_in_json_form_is_allowed(self):
        self.assertEqual(scan('{"EIA_API_' 'KEY": "DEMO_KEY"}'), 0)

    def test_any_other_filled_json_key_is_flagged(self):
        self.assertEqual(scan('{"EIA_API_' 'KEY": "abcdef123"}'), 1)




class ReviewedHistoryFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/check-public.py")
        self.commit("initial")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def write(self, content, name="note.md"):
        (self.root / name).write_text(content)

    def reviewed(self):
        import json
        self.fixture = 'network ' + FLAGGED[0] + '\nREVIEW_SENTINEL\n'
        self.write(self.fixture, 'reviewed-fixture.txt')
        self.commit('reviewed synthetic network fixture')
        self.oid = self.git('hash-object', 'reviewed-fixture.txt')
        (self.root / 'reviewed-fixture.txt').unlink()
        self.commit('remove historical fixture')
        self.manifest = {'version': 1, 'findings': [{'blob_oid': self.oid,
            'path': 'reviewed-fixture.txt', 'kind': 'private address',
            'reason': 'synthetic-network'}]}
        self.manifest_path = self.root / 'scripts/public-history-findings.json'
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.commit('record reviewed finding')

    def scan_history(self):
        return subprocess.run([sys.executable, str(self.root / 'scripts/check-public.py'),
            '--history', 'HEAD'], cwd=self.root, capture_output=True, text=True)

    def test_exact_reviewed_fixture_history_passes(self):
        self.reviewed()
        self.assertEqual(self.scan_history().returncode, 0)

    def test_modified_blob_with_new_credential_still_fails(self):
        import json
        self.reviewed()
        self.write(self.fixture + json.dumps({'password': 'new-synthetic-value'}), 'reviewed-fixture.txt')
        self.commit('modified fixture contains new credential')
        (self.root / 'reviewed-fixture.txt').unlink()
        self.commit('remove modified fixture')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('filled JSON credential', result.stdout)

    def test_new_private_pattern_on_reviewed_blob_still_fails(self):
        self.reviewed()
        self.write('scripts/scrub-private-patterns.txt\n', '.gitignore')
        self.commit('ignore machine pattern catalog')
        self.write('REVIEW_' + 'SENTINEL\n', 'scripts/scrub-private-patterns.txt')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('history:reviewed-fixture.txt — local private pattern', result.stdout)

    def test_current_and_index_are_never_exempt(self):
        self.reviewed()
        self.write(self.fixture, 'reviewed-fixture.txt')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL: reviewed-fixture.txt — private address', result.stdout)
        self.git('add', 'reviewed-fixture.txt')
        self.write('clean\n', 'reviewed-fixture.txt')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL: index:reviewed-fixture.txt — private address', result.stdout)

    def test_same_blob_at_another_path_is_not_exempt(self):
        self.reviewed()
        self.write(self.fixture, 'unreviewed.txt')
        self.commit('reuse fixture at unreviewed path')
        (self.root / 'unreviewed.txt').unlink()
        self.commit('remove unreviewed path')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('history:unreviewed.txt — private address', result.stdout)

    def test_simultaneous_aliases_remain_distinct_in_history(self):
        self.reviewed()
        self.write(self.fixture, 'reviewed-fixture.txt')
        self.write(self.fixture, 'unreviewed.txt')
        self.commit('same bytes at reviewed and unreviewed paths')
        (self.root / 'reviewed-fixture.txt').unlink()
        (self.root / 'unreviewed.txt').unlink()
        self.commit('remove both aliases')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('history:unreviewed.txt — private address', result.stdout)

    def test_gitlinks_do_not_require_external_commit_objects(self):
        self.reviewed()
        self.git('update-index', '--add', '--cacheinfo', '160000,' + '1' * 40 + ',external')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'gitlink')
        self.git('update-index', '--force-remove', 'external')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'remove gitlink')
        self.assertEqual(self.scan_history().returncode, 0)

    def test_historical_paths_with_tabs_and_newlines_are_not_split(self):
        self.reviewed()
        name = 'unreviewed\talias\n.txt'
        self.write(self.fixture, name)
        self.commit('nonstandard historical path')
        (self.root / name).unlink()
        self.commit('remove nonstandard path')
        result = self.scan_history()
        self.assertEqual(result.returncode, 1)
        self.assertIn('history:' + name + ' — private address', result.stdout)

    def test_malformed_manifest_fails_closed(self):
        import json
        self.reviewed()
        invalid = ['{', json.dumps({'version': 2, 'findings': []}),
            json.dumps({'version': 1, 'findings': [{'blob_oid': 'bad'}]}),
            json.dumps({**self.manifest, 'findings': self.manifest['findings'] * 2})]
        for value in invalid:
            with self.subTest(value=value[:20]):
                self.manifest_path.write_text(value)
                self.assertEqual(self.scan_history().returncode, 2)


if __name__ == "__main__":
    unittest.main()
