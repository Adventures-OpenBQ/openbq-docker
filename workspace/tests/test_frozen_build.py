"""Use the recorded backend lock without modifying the pinned source checkout."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import shlex
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/assemble.sh'
PIN = 'be00e95019a55d57af146919ee46b7e1a4859226'

class FrozenBuild(unittest.TestCase):
    def fixture(self, root):
        recipe = root / 'recipe'
        (recipe / 'scripts').mkdir(parents=True)
        shutil.copyfile(SCRIPT, recipe / 'scripts/assemble.sh')
        shutil.copyfile(SCRIPT.parent / 'strip_public_test_key.py', recipe / 'scripts/strip_public_test_key.py')
        lock = b'recorded resolved dependency lock\n'
        (recipe / 'resolved-poetry.lock').write_bytes(lock)
        (recipe / 'source.json').write_text(json.dumps({'observed_build': {'resolved_lock_sha256': hashlib.sha256(lock).hexdigest()}}))
        source = root / 'source'
        for name in ('lite', 'backend-api/backend', 'terminalpro'):
            (source / name).mkdir(parents=True)
        (source / 'lite/Dockerfile').write_text('FROM scratch\n')
        (source / 'backend-api/backend/poetry.lock').write_text('original upstream lock\n')
        (source / 'backend-api/backend/boundary.txt').write_text('upstream fixture\n')
        (source / 'terminalpro/bun.lock').write_text('original frontend lock\n')
        (source / 'terminalpro/.env').write_text('PUBLIC_FEATURE=enabled\n')
        archive = root / 'pinned-source.tar'
        with tarfile.open(archive, 'w') as tracked:
            for name in ('lite', 'backend-api/backend', 'terminalpro'):
                tracked.add(source / name, arcname=name)
        (recipe / 'patches').mkdir()
        (recipe / 'patches/005-workspace-request-boundaries.patch').write_text(
            '--- a/backend/boundary.txt\n+++ b/backend/boundary.txt\n'
            '@@ -1 +1 @@\n-upstream fixture\n+repaired fixture\n')
        (recipe / 'patches/006-public-test-key-packaging.patch').write_text(
            '--- a/Dockerfile\n+++ b/Dockerfile\n'
            '@@ -1 +1,2 @@\n FROM scratch\n+# reviewed fixture cleanup before runtime COPY\n')
        bindir = root / 'bin'
        bindir.mkdir()
        git = bindir / 'git'
        git.write_text(f'#!/bin/sh\ncase "$*" in *rev-parse*) echo {PIN};; *status*) exit 0;; *archive*) cat {shlex.quote(str(archive))};; *) exit 1;; esac\n')
        git.chmod(0o700)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
        return recipe, source, env, lock

    def test_recorded_lock_is_assembled_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, lock = self.fixture(Path(temp))
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((recipe / 'build-context/backend/poetry.lock').read_bytes(), lock)
            self.assertEqual((source / 'backend-api/backend/poetry.lock').read_text(), 'original upstream lock\n')

    def test_corrupt_recorded_lock_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, lock = self.fixture(Path(temp))
            (recipe / 'resolved-poetry.lock').write_bytes(lock + b'changed')
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((recipe / 'build-context').exists())

    def test_ignored_operator_files_are_not_assembled(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            local_paths = ('terminalpro/.env.production.local',
                           'backend-api/backend/envs/runtime.env',
                           'backend-api/backend/ts-state/tailscaled.state')
            for name in local_paths:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('SYNTHETIC_LOCAL_ONLY=do-not-publish\n')
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('terminalpro/.env.production.local', 'backend/envs/runtime.env',
                         'backend/ts-state/tailscaled.state'):
                self.assertFalse((recipe / 'build-context' / name).exists(), name)
            for name in local_paths:
                self.assertTrue((source / name).exists(), name)

    def test_assume_unchanged_working_copy_cannot_override_pinned_input(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            # The frozen archive is the tracked commit. The clean-status fake
            # models Git hiding a modified file marked assume-unchanged.
            (source / 'terminalpro/bun.lock').write_text('local working-copy override\n')
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((recipe / 'build-context/terminalpro/bun.lock').read_text(), 'original frontend lock\n')
            self.assertEqual((source / 'terminalpro/bun.lock').read_text(), 'local working-copy override\n')

    def test_reviewed_tracked_public_environment_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((recipe / 'build-context/terminalpro/.env').read_text(), 'PUBLIC_FEATURE=enabled\n')

    def test_assembly_includes_security_patch_before_build(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((recipe / 'build-context/backend/boundary.txt').read_text(), 'repaired fixture\n')
            self.assertEqual((source / 'backend-api/backend/boundary.txt').read_text(), 'upstream fixture\n')

    def test_invalid_security_patch_leaves_no_partial_context(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            (recipe / 'patches/005-workspace-request-boundaries.patch').write_text('invalid patch\n')
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((recipe / 'build-context').exists())

    def test_fixture_guard_and_packaging_patch_are_assembled(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            guard = recipe / 'build-context/public-test-fixtures/strip_public_test_key.py'
            self.assertTrue(guard.is_file(), 'Build context must include exact fixture guard')
            self.assertEqual(guard.read_bytes(), (SCRIPT.parent / 'strip_public_test_key.py').read_bytes())
            self.assertIn('reviewed fixture cleanup', (recipe / 'build-context/Dockerfile').read_text())

    def test_invalid_fixture_patch_leaves_no_partial_context(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env, _ = self.fixture(Path(temp))
            (recipe / 'patches/006-public-test-key-packaging.patch').write_text('invalid patch\n')
            result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((recipe / 'build-context').exists())

if __name__ == '__main__':
    unittest.main()
