# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from assemble import assemble

class AssemblyTests(unittest.TestCase):
    def test_wrong_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch('assemble.subprocess.check_output', return_value='0' * 40):
            output = Path(tmp) / 'out'
            with self.assertRaisesRegex(ValueError, 'revision'):
                assemble(Path(tmp), output)
            self.assertFalse(output.exists())
    def test_dirty_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch('assemble.subprocess.check_output', side_effect=['a6293707576e16edda8305adda95b07b6a4b968b', ' M core.py']):
            output = Path(tmp) / 'out'
            with self.assertRaisesRegex(ValueError, 'clean'):
                assemble(Path(tmp), output)
            self.assertFalse(output.exists())
    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, patch('assemble.subprocess.check_output', side_effect=['a6293707576e16edda8305adda95b07b6a4b968b', '']):
            output = Path(tmp) / 'out'
            output.mkdir()
            marker = output / 'marker'
            marker.write_text('keep')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                assemble(Path(tmp), output)
            self.assertEqual(marker.read_text(), 'keep')
