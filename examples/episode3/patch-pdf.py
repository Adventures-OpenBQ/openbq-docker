#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Carry forward the reference fork's PDF repair, using immutable asset URLs.

The S3 bucket returns AllAccessDisabled. Assets are the same upstream PDFs,
retained by bdobb-dev/backends-for-openbb at the previously qualified pin.
Fail closed if upstream no longer has the three expected links.
"""
from pathlib import Path
import sys
path = Path(sys.argv[1])
source = path.read_text()
prefix = "https://openbb-assets.s3.us-east-1.amazonaws.com/testing/"
mirror = "https://raw.githubusercontent.com/bdobb-dev/backends-for-openbb/32615f789f9423ea14d3f95003da250f4ef5bcfc/getting-started/reference-backend/"
for name, count in [("sample.pdf", 2), ("bitcoin.pdf", 1)]:
    old = prefix + name
    if source.count(old) != count:
        raise SystemExit("PDF fixture links changed; review the source before patching")
    source = source.replace(old, mirror + name)
path.write_text(source)
