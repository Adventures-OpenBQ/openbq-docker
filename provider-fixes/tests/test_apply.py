# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Installer guards reject drift before changing any installed provider source."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch


class ApplyGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.overlay = root / "overlay"
        self.site = root / "site"
        self.overlay.mkdir()
        self.site.mkdir()
        self.installer = self.overlay / "apply.py"
        shutil.copyfile(Path(__file__).parents[1] / "apply.py", self.installer)
        self.preimage = b"published provider source\n"
        self.replacement = b"reviewed provider source\n"
        self.relative = "openbb_core/provider.py"
        self.declarations = {}
        self.add_source(self.relative, self.preimage)

    def add_source(self, name, original):
        source = self.overlay / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(self.replacement)
        self.declarations[name] = hashlib.sha256(original).hexdigest() if original is not None else None
        if original is not None:
            target = self.site / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
        (self.overlay / "original-sha256.json").write_text(json.dumps(self.declarations))

    def run_apply(self, versions=None):
        overrides = versions or {}

        def installed_version(package):
            return overrides.get(package, {
                "openbb-core": "2.0.1", "openbb-platform-api": "2.0.1",
                "openbb-technical": "2.0.1", "openbb-imf": "3.0.0",
            }.get(package, "2.0.0"))

        with patch("sysconfig.get_paths", return_value={"purelib": str(self.site)}), \
                patch("importlib.metadata.version", side_effect=installed_version), \
                contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(self.installer), run_name="__main__")

    def test_newly_supported_package_version_drift_is_rejected_before_copy(self):
        with self.assertRaisesRegex(SystemExit, "Unexpected version for openbb-ecb"):
            self.run_apply({"openbb-ecb": "99.0.0"})
        self.assertEqual((self.site / self.relative).read_bytes(), self.preimage)

    def test_absent_source_can_be_added_in_a_new_package_directory(self):
        self.add_source("openbb_cboe/utils/shared_cache.py", None)
        self.run_apply()
        self.assertEqual((self.site / "openbb_cboe/utils/shared_cache.py").read_bytes(),
                         self.replacement)
        self.assertEqual((self.site / self.relative).read_bytes(), self.replacement)

    def test_existing_source_cannot_be_overwritten_by_an_absent_file_guard(self):
        relative = "openbb_cboe/utils/shared_cache.py"
        self.add_source(relative, None)
        target = self.site / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"unexpected installed source\n")
        with self.assertRaises(SystemExit):
            self.run_apply()
        self.assertEqual(target.read_bytes(), b"unexpected installed source\n")
        self.assertEqual((self.site / self.relative).read_bytes(), self.preimage)

    def test_changed_package_preimage_rejects_the_entire_install(self):
        self.add_source("openbb_cboe/other.py", b"second published source\n")
        (self.site / "openbb_cboe/other.py").write_bytes(b"newer local source\n")
        with self.assertRaisesRegex(SystemExit, "Baseline mismatch"):
            self.run_apply()
        self.assertEqual((self.site / self.relative).read_bytes(), self.preimage)
        self.assertEqual((self.site / "openbb_cboe/other.py").read_bytes(),
                         b"newer local source\n")

    def test_provider_overlay_preserves_unrelated_v11_capture_namespaces(self):
        for package in ("openbq_eodhd", "openbq_yfinance"):
            target = self.site / package / "capture.py"
            target.parent.mkdir()
            target.write_bytes(b"maintained v11 capture\n")
        self.run_apply()
        self.assertEqual((self.site / self.relative).read_bytes(), self.replacement)
        for package in ("openbq_eodhd", "openbq_yfinance"):
            self.assertEqual((self.site / package / "capture.py").read_bytes(),
                             b"maintained v11 capture\n")
