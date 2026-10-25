# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Apply reviewed provider sources only to the exact published baseline."""
import hashlib, json, shutil, sysconfig
from pathlib import Path
from importlib.metadata import version
root = Path(__file__).parent
site = Path(sysconfig.get_paths()["purelib"])
for package, expected in (("openbb-bls", "2.0.0"), ("openbb-cboe", "2.0.0"), ("openbb-cftc", "2.0.0"), ("openbb-core", "2.0.1"), ("openbb-deribit", "2.0.0"), ("openbb-famafrench", "2.0.0"), ("openbb-federal-reserve", "2.0.0"), ("openbb-finra", "2.0.0"), ("openbb-fred", "2.0.0"), ("openbb-government-us", "2.0.0"), ("openbb-nasdaq", "2.0.0"), ("openbb-sec", "2.0.0"), ("openbb-tmx", "2.0.0"), ("openbb-us-eia", "2.0.0")):
    if version(package) != expected:
        raise SystemExit(f"Unexpected version for {package}")
files = json.loads((root / "original-sha256.json").read_text())
for name, expected in files.items():
    target = site / name
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise SystemExit(f"Baseline mismatch: {name}")
for name in files:
    shutil.copyfile(root / name, site / name)
print(f"Applied {len(files)} reviewed provider source files")
