# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Build gate: openbb-eodhd on the locked ODP, with the SDK boundary stubbed.

Dockerfile.v3 copies this file next to v9/eodhd/tests and runs it after
openbb-build. No EODHD key and no network are used.
"""
import importlib.metadata as metadata
import sys
import unittest
from pathlib import Path

assert metadata.version('openbb-core') == '2.0.1'
assert metadata.version('openbb-platform-api') == '2.0.1'
assert metadata.version('openbb-eodhd') == '9.6.3'
# The official EODHD SDK, built from the commit openbb-eodhd's pyproject pins.
metadata.version('eodhd')
from eodhd import APIClient  # noqa: E402

client = APIClient('demo')
# openbb_eodhd.models._client configures these SDK internals (see its tests/test_client.py).
assert hasattr(client, '_session') and hasattr(client, '_timeout'), 'EODHD SDK pin moved'
# This line ships no standard routers; obb.eodhd.* is the EODHD namespace.
for name in ('openbb-equity', 'openbb-etf', 'openbb-economy'):
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        continue
    raise AssertionError(f'{name} is installed; v9/eodhd/tests assume no standard routers')

suite = unittest.defaultTestLoader.discover(str(Path(__file__).with_name('tests')))
result = unittest.TextTestRunner(verbosity=1).run(suite)
if not result.wasSuccessful():
    sys.exit(1)
print('PASS: openbb-eodhd 9.6.3, 52 obb.eodhd.* mirrors, the EODHD app, a stubbed price query, and the app under OPENBB_API_AUTH')
