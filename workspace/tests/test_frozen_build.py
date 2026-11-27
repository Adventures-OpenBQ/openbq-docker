"""Assembly reads the pinned Git object, preserving working-copy operator state."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/assemble.sh'
PIN = 'be00e95019a55d57af146919ee46b7e1a4859226'


class FrozenAssembly(unittest.TestCase):
    def fixture(self, root):
        recipe = root / 'recipe'
        (recipe / 'scripts').mkdir(parents=True)
        (recipe / 'scripts/assemble.sh').write_bytes(SCRIPT.read_bytes())
        source = root / 'source'
        for name in ('lite', 'backend-api/backend', 'terminalpro'):
            (source / name).mkdir(parents=True)
        (source / 'lite/Dockerfile').write_text('FROM scratch\n')
        (source / 'backend-api/backend/poetry.lock').write_text('original lock\n')
        (source / 'terminalpro/bun.lock').write_text('original frontend lock\n')
        (source / 'terminalpro/.env').write_text('PUBLIC_FEATURE=enabled\n')
        archive = root / 'pinned-source.tar'
        with tarfile.open(archive, 'w') as tracked:
            for name in ('lite', 'backend-api/backend', 'terminalpro'):
                tracked.add(source / name, arcname=name)
        bindir = root / 'bin'
        bindir.mkdir()
        wrapper = bindir / 'git'
        wrapper.write_text('#!/bin/sh\ncase "$*" in\n'
                           f'*rev-parse*) echo {PIN};;\n'
                           '*status*) exit 0;;\n'
                           f'*archive*) cat {shlex.quote(str(archive))};;\n'
                           '*) exit 1;;\nesac\n')
        wrapper.chmod(0o700)
        return recipe, source, dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])

    def assemble(self, recipe, source, env):
        result = subprocess.run(['bash', str(recipe / 'scripts/assemble.sh'), str(source)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return recipe / 'build-context'

    def test_ignored_operator_files_are_excluded_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env = self.fixture(Path(temp))
            local = source / 'terminalpro/.env.production.local'
            local.write_text('SYNTHETIC_LOCAL_ONLY=operator-state\n')
            context = self.assemble(recipe, source, env)
            self.assertFalse((context / 'terminalpro/.env.production.local').exists())
            self.assertTrue(local.exists())
            self.assertEqual((context / 'terminalpro/.env').read_text(), 'PUBLIC_FEATURE=enabled\n')

    def test_assume_unchanged_checkout_cannot_override_pinned_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe, source, env = self.fixture(Path(temp))
            (source / 'terminalpro/bun.lock').write_text('local override\n')
            context = self.assemble(recipe, source, env)
            self.assertEqual((context / 'terminalpro/bun.lock').read_text(), 'original frontend lock\n')
            self.assertEqual((source / 'terminalpro/bun.lock').read_text(), 'local override\n')
            record = json.loads((context / '.workspace-source.json').read_text())
            self.assertEqual(record['files']['terminalpro/bun.lock'], hashlib.sha256(b'original frontend lock\n').hexdigest())
