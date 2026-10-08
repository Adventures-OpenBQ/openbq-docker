"""scripts/check-public.py address rules (stdlib unittest; run: python3 -m unittest discover tests).

Fixtures are split so this file does not trip the scanner it tests.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-public.py"
FLAGGED = ["fd7a:115c:a1e0:" "ab12:4843:cd96:625b:1234", "fd7a:115c:a1e0:" ":1"]


def scan(text):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        Path(d, "note.md").write_text(text + "\n")
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=d, capture_output=True, text=True).returncode


class Addresses(unittest.TestCase):
    def test_tailnet_ipv6_addresses_are_flagged(self):
        for addr in FLAGGED:
            with self.subTest(addr=addr):
                self.assertEqual(scan("peer " + addr), 1)

    def test_the_bare_ula_prefix_is_not_an_address(self):
        self.assertEqual(scan("fd7a:115c:a1e0::/48"), 0)


if __name__ == "__main__":
    unittest.main()
