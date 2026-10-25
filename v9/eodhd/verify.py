# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Build gate: openbq-eodhd on the locked ODP, with the SDK boundary stubbed.

The Dockerfile's api stage copies this file next to v9/eodhd/tests and runs it after
openbb-build. No EODHD key and no network are used.
"""
import importlib.metadata as metadata
import importlib.util
import unittest
from pathlib import Path

assert metadata.version('openbb-core') == '2.0.1'
assert metadata.version('openbb-platform-api') == '2.0.1'
assert metadata.version('openbq-eodhd') == '9.0.1'
# The official EODHD SDK, vendored inside openbq-eodhd (upstream commit f98e69d).
# Nothing installs it separately: a top-level `eodhd` would mean a stray SDK beside the vendored one.
assert importlib.util.find_spec('eodhd') is None, 'a separate eodhd package is installed'
from openbq_eodhd._vendor.eodhd import APIClient  # noqa: E402

client = APIClient('demo')
# openbq_eodhd.models._client configures these SDK internals (see its tests/test_client.py).
assert hasattr(client, '_session') and hasattr(client, '_timeout'), 'EODHD SDK pin moved'
# This line ships no standard routers; obb.eodhd.* is the EODHD namespace.
stray = {'openbb-equity', 'openbb-etf', 'openbb-economy'} & {d.metadata['Name'] for d in metadata.distributions()}
assert not stray, f'{sorted(stray)} installed; v9/eodhd/tests assume no standard routers'

suite = unittest.defaultTestLoader.discover(str(Path(__file__).with_name('tests')))
assert unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
print('PASS: openbq-eodhd 9.0.1, 52 obb.eodhd.* mirrors, the EODHD app, a stubbed price query, and the app under OPENBB_API_AUTH')
