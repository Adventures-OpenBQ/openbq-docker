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

    def test_a_replace_with_placeholder_is_allowed(self):
        """An example file's REPLACE_WITH_... value is a placeholder, not a credential
        (an old settings.example.json on an unmerged branch failed CI's all-refs scan)."""
        self.assertEqual(scan('{"gateway_' 'token": "REPLACE_WITH_A_LONG_RANDOM_TOKEN"}'), 0)
        self.assertEqual(scan('{"gateway_' 'token": "replace_with_a_real_value_9f2"}'), 1)
class PushHistory(unittest.TestCase):
    """Exercise the actual pre-push hook with Git's update protocol."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/check-public.py")
        self.hook = self.root / ".git/hooks/pre-push"
        shutil.copyfile(SCRIPT.parent.parent / ".githooks/pre-push", self.hook)
        self.base = self.commit("initial")
        self.zero = "0" * len(self.base)
        self.bad = "https://" + ".".join(["fixture", "private-demo", "ts", "net"])

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def write(self, content, name="note.md"):
        (self.root / name).write_text(content)
        return self.commit("fixture")

    def record(self, local, remote, local_ref="refs/heads/fixture", remote_ref="refs/heads/fixture"):
        return f"{local_ref} {local} {remote_ref} {remote}\n"

    def hook_result(self, records):
        result = subprocess.run(["sh", str(self.hook)], cwd=self.root, input=records, capture_output=True, text=True)
        self.assertNotIn(self.bad, result.stdout + result.stderr)
        return result

    def assert_exit(self, records, expected):
        result = self.hook_result(records)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def history_with_removed_bad(self):
        bad_commit = self.write(self.bad)
        clean = self.write("sanitized")
        return bad_commit, clean

    def test_remote_reachable_removed_blob_does_not_block_new_clean_push(self):
        remote, clean = self.history_with_removed_bad()
        self.assert_exit(self.record(clean, remote), 0)

    def test_new_removed_bad_blob_still_blocks_push(self):
        _, clean = self.history_with_removed_bad()
        result = self.assert_exit(self.record(clean, self.base), 1)
        self.assertIn("history:note.md", result.stdout)

    def test_new_bad_tip_blocks_push(self):
        bad = self.write(self.bad)
        self.assert_exit(self.record(bad, self.base), 1)

    def test_zero_remote_new_branch_scans_all_reachable_history(self):
        _, clean = self.history_with_removed_bad()
        self.assert_exit(self.record(clean, self.zero), 1)

    def test_multiple_updates_union_only_the_supplied_remote_roots(self):
        remote, clean = self.history_with_removed_bad()
        other = self.write("second branch", "other.md")
        records = self.record(clean, self.zero) + self.record(other, remote, "HEAD~1", "refs/heads/other")
        self.assert_exit(records, 0)
        # An unrelated local ref does not excuse a newly introduced bad blob.
        self.git("branch", "unrelated", remote)
        self.assert_exit(self.record(other, self.base), 1)

    def test_multiple_updates_scan_new_objects_from_every_local_root(self):
        remote = self.write("remote")
        bad = self.write(self.bad)
        clean = self.write("clean again")
        records = self.record(remote, self.base) + self.record(bad, remote, "HEAD~1", "refs/heads/other")
        self.assert_exit(records, 1)
        self.assertNotEqual(clean, bad)

    def test_empty_input_and_delete_only_keep_working_and_index_scan(self):
        remote, clean = self.history_with_removed_bad()
        self.assert_exit("", 0)
        deletion = self.record(self.zero, remote, "(delete)")
        self.assert_exit(deletion, 0)
        (self.root / "note.md").write_text(self.bad)
        self.assert_exit(deletion, 1)
        self.git("add", "note.md")
        (self.root / "note.md").write_text("clean working copy")
        self.assert_exit(deletion, 1)
        self.assert_exit("", 1)

    def test_mixed_delete_and_update_uses_actual_supplied_remote_roots(self):
        remote, clean = self.history_with_removed_bad()
        records = self.record(self.zero, remote, "(delete)") + self.record(clean, self.zero, "HEAD", "refs/heads/other")
        self.assert_exit(records, 0)

    def test_exclusion_never_bypasses_current_working_or_index_checks(self):
        remote = self.write(self.bad)
        self.assert_exit(self.record(remote, remote), 1)
        (self.root / "note.md").write_text("clean working copy")
        self.assert_exit(self.record(remote, remote), 1)

    def test_annotated_tags_and_revision_ref_metadata_are_supported(self):
        remote, clean = self.history_with_removed_bad()
        for name, oid in (("remote-tag", remote), ("local-tag", clean)):
            self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "tag", "-a", name, oid, "-m", "fixture tag")
        old_tag = self.git("rev-parse", "remote-tag")
        new_tag = self.git("rev-parse", "local-tag")
        self.assert_exit(self.record(new_tag, old_tag, "refs/tags/local-tag", "refs/tags/local-tag"), 0)
        self.assert_exit(self.record(clean, old_tag, "HEAD~0"), 0)
        self.assert_exit(self.record(clean, old_tag, clean), 0)

    def test_malformed_nonempty_protocol_fails_closed(self):
        invalid = [
            "\n", "bad record " + self.bad + "\n", self.record(self.zero, self.zero),
            self.record(self.base[:-1], self.zero),
            self.record("g" * len(self.base), self.zero),
            self.record(self.base, "f" * len(self.base)),
            self.record("f" * len(self.base), self.zero),
            self.record(self.base, "--all"),
            self.record(self.base, self.zero) + "\n",
            self.record(self.base, self.zero).rstrip() + " extra\n",
        ]
        for record in invalid:
            with self.subTest(record=record):
                self.assert_exit(record, 2)

    def test_non_commit_object_root_fails_closed(self):
        blob = self.git("rev-parse", "HEAD:scripts/check-public.py")
        self.assert_exit(self.record(blob, self.zero), 2)

    def test_explicit_full_history_mode_remains_available(self):
        self.history_with_removed_bad()
        result = subprocess.run([sys.executable, str(SCRIPT), "--history"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("history:note.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
