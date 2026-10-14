# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""credentials.demo.env holds only public demo keys, and Compose loads it before credentials.env.

stdlib unittest (plus PyYAML, pinned in requirements.lock); run: python3 -m unittest discover tests.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "credentials.demo.env"
# The only names and values the file may hold: each provider's own published demo key
# (docs/credentials-demo-receipt.md). EODHD's "demo" joins on the line that ships openbq-eodhd (v9).
ALLOWED = {
    "EIA_API_KEY": "DEMO_KEY",
    "CONGRESS_GOV_API_KEY": "DEMO_KEY",
}


def assignments(text):
    pairs = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(\S+)", line)
        if not match:
            raise AssertionError(f"not a NAME=value line: {line!r}")
        pairs.append(match.groups())
    return pairs


class DemoFile(unittest.TestCase):
    def test_only_the_allowed_public_names_and_values(self):
        pairs = assignments(DEMO.read_text())
        self.assertEqual(len(pairs), len(dict(pairs)), "a name appears twice")
        self.assertEqual(dict(pairs), ALLOWED)

    def test_the_file_is_tracked_and_stays_out_of_the_image(self):
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "credentials.demo.env"], cwd=ROOT,
                                 capture_output=True)
        self.assertEqual(tracked.returncode, 0, "credentials.demo.env must be committed")
        self.assertIn("*.env", (ROOT / ".dockerignore").read_text().split())

    def test_the_example_leaves_demo_covered_names_commented(self):
        # An empty NAME= in credentials.env would override the demo key with nothing.
        example = (ROOT / "credentials.env.example").read_text()
        for name in ALLOWED:
            self.assertNotRegex(example, rf"(?m)^{name}=")
            self.assertRegex(example, rf"(?m)^# {name}=$")

    def test_check_public_accepts_the_file_and_nothing_else_like_it(self):
        script = (ROOT / "scripts" / "check-public.py").read_text()
        for name, value in ALLOWED.items():
            self.assertIn(f"('{name}','{value}')", script)
        result = subprocess.run([sys.executable, "scripts/check-public.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotIn("credentials.demo.env", result.stdout)


class ComposeOrder(unittest.TestCase):
    def test_every_service_loading_credentials_env_loads_the_demo_file_first(self):
        try:
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("PyYAML required")
        checked = 0
        for compose in sorted([*ROOT.glob("*compose*.yml"), *ROOT.glob("*compose*.yaml")]):
            services = (yaml.safe_load(compose.read_text()) or {}).get("services") or {}
            for name, service in services.items():
                files = service.get("env_file") or []
                files = [files] if isinstance(files, (str, dict)) else files
                paths = [f if isinstance(f, str) else f.get("path") for f in files]
                if "./credentials.env" not in paths:
                    continue
                checked += 1
                with self.subTest(compose=compose.name, service=name):
                    demo = paths.index("./credentials.demo.env")
                    self.assertLess(demo, paths.index("./credentials.env"))
                    self.assertIs(files[demo].get("required"), True)
                    self.assertIs(files[paths.index("./credentials.env")].get("required"), False)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
