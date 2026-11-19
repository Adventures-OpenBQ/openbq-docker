# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Compare the vendored files to the SHA-256 inventory of the pinned Git tree."""
import hashlib
import json
from pathlib import Path


def test_vendored_source_matches_pinned_manifest():
    package = Path(__file__).resolve().parents[1]
    pin = json.loads((package / "source.json").read_text())
    assert pin["commit"] == "349f2de40773cf2e1d9e2993ebabf3184871c07d"
    source = package / "source"
    vendored_manifest = {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file() and not {"__pycache__", ".pytest_cache", ".ruff_cache"}.intersection(path.parts)
    }
    assert vendored_manifest == pin["files_sha256"]
