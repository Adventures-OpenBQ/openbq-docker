# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The TemporalDB pin: the lock, its provenance and every compose file name one local image (stdlib unittest)."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TemporalDbPin(unittest.TestCase):
    def test_lock_provenance_and_compose_name_one_image(self):
        lock = json.loads((ROOT / 'v11/temporaldb.lock.json').read_text())
        self.assertEqual(lock['version'], '0.5.0')
        self.assertEqual(lock['provenance']['image_id'], lock['image_id'])
        self.assertEqual(lock['provenance']['source_commit'], lock['source_commit'])
        self.assertEqual(lock['provenance']['labels']['org.opencontainers.image.revision'], lock['source_commit'])
        self.assertEqual(lock['provenance']['labels']['org.opencontainers.image.version'], lock['version'])
        self.assertEqual(lock['artifact'], f"temporaldb-{lock['version']}-linux-arm64.docker.tar")
        self.assertIsNone(lock['registry_reference'])
        for name in ('v11/compose.temporaldb.yaml', 'v11/compose.temporaldb-mcp.yaml'):
            self.assertEqual(set(re.findall(r'image: (sha256:[0-9a-f]{64})', (ROOT / name).read_text())), {lock['image_id']}, name)


if __name__ == '__main__':
    unittest.main()
