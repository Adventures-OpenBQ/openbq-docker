# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Compare the vendored files to the SHA-256 inventory of the pinned Git tree."""
import hashlib
import json
from pathlib import Path


def test_vendored_source_matches_pinned_manifest():
    package = Path(__file__).resolve().parents[1]
    pin = json.loads((package / "source.json").read_text())
    assert pin["commit"] == "6f9f1cb20475c3204867bf03c3f3dc5f7141ca96"
    source = package / "source"
    vendored_manifest = {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file() and not {"__pycache__", ".pytest_cache", ".ruff_cache"}.intersection(path.parts)
    }
    assert vendored_manifest == pin["files_sha256"]
