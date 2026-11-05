# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The arts-charts pin: the lock names the vendored tree, and the image is built from it alone."""
import importlib.util
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'v12/arts-charts'
LOCK = json.loads((ROOT / 'v12/arts-charts.lock.json').read_text())
spec = importlib.util.spec_from_file_location('vendor', HERE / 'vendor.py')
vendor = importlib.util.module_from_spec(spec); spec.loader.exec_module(vendor)


def test_the_lock_names_the_vendored_tree_exactly():
    assert re.fullmatch(r'[0-9a-f]{40}', LOCK['source_commit'])
    assert LOCK['tag'] is None or re.fullmatch(r'v\d+\.\d+\.\d+', LOCK['tag'])
    assert LOCK['image'] == 'openbq-arts-charts:12.0.0'
    assert LOCK['license'] == 'BUSL-1.1'
    assert LOCK['paths'] == vendor.PATHS
    assert LOCK['source_tree_sha256'] == vendor.tree_hash(HERE / 'source')


def test_the_snapshot_carries_its_busl_licence_and_no_tests():
    assert 'Business Source License 1.1' in (HERE / 'source/LICENSE').read_text()
    names = [p.relative_to(HERE / 'source').as_posix() for p in (HERE / 'source').rglob('*') if p.is_file()]
    assert not [n for n in names if vendor.excluded(n)]


def test_requirements_in_is_the_servers_dependencies_plus_its_runtime():
    project = tomllib.loads((HERE / 'source/server/pyproject.toml').read_text())['project']
    # openbq-ta is installed from this repository's live-grid/openbq-ta (the Dockerfile's `openbq-ta` context), not locked.
    wanted = (set(project['dependencies']) - {'openbq-ta==0.1.0'}) | set(project['optional-dependencies']['postgres']) \
        | set(project['optional-dependencies']['snapshots']) | {'uvicorn[standard]>=0.29', 'websockets>=14'}
    lines = {l.strip() for l in (HERE / 'requirements.in').read_text().splitlines() if l.strip() and not l.startswith('#')}
    assert lines == wanted
    assert '--hash=sha256:' in (HERE / 'requirements.lock').read_text()


def test_the_image_installs_hashed_pins_chromium_and_the_render_page():
    text = (HERE / 'Dockerfile').read_text()
    assert re.search(r'FROM node:24[\w.-]*@sha256:[0-9a-f]{64} AS render', text)
    assert 'FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1' in text
    assert 'pnpm install --frozen-lockfile' in text and 'vite build -c vite.render.config.ts' in text
    assert 'pip install --require-hashes --no-deps -r /tmp/requirements.lock' in text
    assert 'pip install --no-deps /srv/server' in text
    assert 'playwright install --with-deps --only-shell chromium' in text
    assert 'USER 10001:10001' in text
