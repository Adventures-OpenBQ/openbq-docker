# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Build gate: the ported EconDB provider on the locked ODP, EconDB's HTTP stubbed.

The Dockerfile copies this file next to v3/econdb/tests and run it after openbb-build.
"""
import importlib.metadata as metadata
import sys
import unittest
from pathlib import Path

assert metadata.version('openbb-core') == '2.0.1'
assert metadata.version('openbb-econdb') == '1.0.0+openbq.1'
suite = unittest.defaultTestLoader.discover(str(Path(__file__).with_name('tests')))
if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
    sys.exit(1)
print('PASS: openbb-econdb 1.0.0+openbq.1, econdb_economy_indicators_econdb_obb keyless, a stubbed RGDP query')
