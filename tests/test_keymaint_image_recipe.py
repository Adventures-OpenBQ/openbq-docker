# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Release recipe guards for key-maint's independently built image."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYMAINT = ROOT / "key-maint"


class KeyMaintImageRecipe(unittest.TestCase):
    def test_base_matches_the_qualified_api_digest(self):
        recipe = (KEYMAINT / "Dockerfile").read_text()
        base = re.search(r"(?m)^FROM (\S+)", recipe).group(1)
        self.assertRegex(base, r"^python:3\.12-slim@sha256:[0-9a-f]{64}$")
        self.assertIn(f"FROM {base} AS odp", (ROOT / "Dockerfile").read_text())

    def test_runtime_and_builder_inputs_are_exact_pins(self):
        for filename in ("requirements.lock", "requirements-build.lock"):
            path = KEYMAINT / filename
            self.assertTrue(path.is_file(), f"missing {filename}")
            entries = [line for line in path.read_text().splitlines()
                       if line.strip() and not line.startswith("#")]
            self.assertTrue(entries, filename)
            for entry in entries:
                self.assertRegex(entry, r"^[A-Za-z0-9_.-]+==[A-Za-z0-9.+_-]+$")
        pins = (KEYMAINT / "requirements-build.lock").read_text()
        self.assertIn("setuptools==", pins)
        self.assertIn("pip==", pins)
        pins = (KEYMAINT / "requirements.lock").read_text()
        for name in ("fastapi", "uvicorn", "httpx"):
            self.assertIn(name + "==", pins)

    def test_install_cannot_resolve_unpinned_build_or_runtime_packages(self):
        recipe = (KEYMAINT / "Dockerfile").read_text().replace("\\\n", " ")
        self.assertIn("COPY requirements.lock requirements-build.lock ./", recipe)
        self.assertIn("python -m pip install --no-deps -r requirements-build.lock -r requirements.lock", recipe)
        self.assertIn("python -m pip install --no-deps --no-build-isolation .", recipe)
        self.assertIn("python -m pip check", recipe)


if __name__ == "__main__":
    unittest.main()
