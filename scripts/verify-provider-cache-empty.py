#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Reject provider cache files left behind by image build-time checks."""
from pathlib import Path
import json

home = Path.home()
roots = [home / 'OpenBBUserData/cache', home / '.openbb_platform/cache', home / '.cache']
counts = {str(root): sum(path.is_file() for path in root.rglob('*')) for root in roots}
if any(counts.values()):
    raise SystemExit('Build-time provider cache files remain: ' + json.dumps(counts))
print('PASS: image contains no provider cache files; normal volume ownership initialization is preserved.')
