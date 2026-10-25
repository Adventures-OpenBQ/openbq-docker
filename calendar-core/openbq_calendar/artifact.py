# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Offline, reproducible contract export; retained by clients and future SQL tests."""

from pathlib import Path
from hashlib import sha256
from .canonical import canonical_bytes
from .contracts import CalendarBundle


def export_contract(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    resources = Path(__file__).parent / "resources"
    data = {"calendar-v1.schema.json": canonical_bytes(CalendarBundle.model_json_schema())}
    for path in sorted(resources.rglob("*.json")):
        if path.name != "calendar-v1.schema.json":
            data[str(path.relative_to(resources))] = path.read_bytes()
    license_path = resources / "LICENSE"
    if license_path.exists():
        data["LICENSE"] = license_path.read_bytes()
    for name, body in data.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    manifest = {
        "artifactVersion": 1,
        "contractVersion": 1,
        "files": [
            {"path": name, "sha256": sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in sorted(data.items())
        ],
    }
    (destination / "manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest


if __name__ == "__main__":
    import sys

    export_contract(sys.argv[1])
