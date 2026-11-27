# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""The build cache gate rejects persisted responses without exposing their data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-provider-cache-empty.py'


class ProviderCacheImageGate(unittest.TestCase):
    def run_gate(self, home):
        return subprocess.run([sys.executable, str(SCRIPT)],
                              env={**os.environ, 'HOME': str(home)},
                              capture_output=True, text=True, check=False)

    def test_clean_image_accepts_normal_application_seed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / 'OpenBBUserData').mkdir()
            seed = home / 'OpenBBUserData/user_settings.json'
            seed.write_text('{"preferences": {}}')
            result = self.run_gate(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(seed.read_text(), '{"preferences": {}}')

    def test_cached_response_is_refused_without_printing_or_removing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cache = home / 'OpenBBUserData/cache/provider'
            cache.mkdir(parents=True)
            response = cache / 'response.json'
            response.write_text('synthetic-private-response-body')
            result = self.run_gate(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cache files remain', result.stderr)
            self.assertNotIn('synthetic-private-response-body', result.stdout + result.stderr)
            self.assertEqual(response.read_text(), 'synthetic-private-response-body')
