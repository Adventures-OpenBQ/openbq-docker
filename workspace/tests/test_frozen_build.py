"""Use the recorded backend lock without modifying the pinned source checkout."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/assemble.sh'
PIN = 'be00e95019a55d57af146919ee46b7e1a4859226'

class FrozenBuild(unittest.TestCase):
    def fixture(self, root):
        recipe = root / 'recipe'
        (recipe / 'scripts').mkdir(parents=True)
        shutil.copyfile(SCRIPT, recipe / 'scripts/assemble.sh')
        lock = b'recorded resolved dependency lock\n'
        (recipe / 'resolved-poetry.lock').write_bytes(lock)
        (recipe / 'source.json').write_text(json.dumps({'observed_build': {'resolved_lock_sha256': hashlib.sha256(lock).hexdigest()}}))
        source = root / 'source'
        for name in ('lite', 'backend-api/backend', 'terminalpro'):
            (source / name).mkdir(parents=True)
        (source / 'lite/Dockerfile').write_text('FROM scratch\n')
        (source / 'backend-api/backend/poetry.lock').write_text('original upstream lock\n')
        (source / 'terminalpro/bun.lock').write_text('original frontend lock\n')
        bindir = root / 'bin'
        bindir.mkdir()
        git = bindir / 'git'
        git.write_text(f'#!/bin/sh\ncase "$*" in *rev-parse*) echo {PIN};; *status*) exit 0;; *) exit 1;; esac\n')
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

if __name__ == '__main__':
    unittest.main()
