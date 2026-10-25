# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""scripts/check-public.py address rules (stdlib unittest; run: python3 -m unittest discover tests).

Fixtures are split so this file does not trip the scanner it tests.
"""
import subprocess
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


if __name__ == "__main__":
    unittest.main()
