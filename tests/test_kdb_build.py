# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The kdb-x recipe and its compose override: a build path that ships no KX software."""
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
OVERRIDE = yaml.safe_load((ROOT / 'compose.kdb-build.yml').read_text())
DOCKERFILE = (ROOT / 'kdb-x' / 'Dockerfile').read_text()


def test_the_recipe_ships_no_kx_binary_and_no_licence():
    tracked = subprocess.run(['git', 'ls-files', 'kdb-x'], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    assert sorted(tracked) == ['kdb-x/Dockerfile', 'kdb-x/README.md', 'kdb-x/entrypoint.sh']


def test_the_build_downloads_from_kx_and_deletes_any_licence_in_the_same_layer():
    assert 'https://portal.dl.kx.com/assets/raw/kdb-x/kdb-x/${KX_VERSION}/${KXP}.zip' in DOCKERFILE
    run = DOCKERFILE.split('RUN set -eux;', 1)[1].split('\nCOPY', 1)[0]
    assert "-name '*.lic'" in run and '-delete' in run
    # A wrong-architecture q fails the build instead of shipping.
    assert 'e_machine' in run and 'arch mismatch' in run
    assert 'COPY kc.lic' not in DOCKERFILE and 'QLIC=' not in DOCKERFILE.split('ENV', 1)[1]


def test_the_override_builds_kdb_locally_and_changes_nothing_else():
    # REVIEW (user ruling 2026-10-14: the kdb tier is openbq-kdb, vendored in v10/kdb/source): the service
    # is renamed kdb -> openbq-kdb and kdb-ws/ is the vendored q/; the same facts are asserted.
    kdb = OVERRIDE['services']['openbq-kdb']
    assert set(OVERRIDE['services']) == {'openbq-kdb'} and set(kdb) == {'build', 'image'}
    assert kdb['build']['context'] == 'kdb-x' and kdb['image'] == 'openbq-kdb-x:local'
    assert kdb['build']['args'] == {'KX_VERSION': '${KX_VERSION:-~latest~}'}
    # Without the override, the stack pulls the maintainer's private image, pinned by digest (D2).
    assert BASE['services']['openbq-kdb']['image'] == '${KDB_IMAGE:-ghcr.io/artcashin/kdb-x:amd64@sha256:013490f90a166e0863651f2c8a7f5d24e8d1beec68d2e3e541c1a2281653a77c}'
    assert 'build' not in BASE['services']['openbq-kdb']


def test_the_entrypoint_runs_the_stacks_script_on_the_stacks_port():
    entry = (ROOT / 'kdb-x' / 'entrypoint.sh').read_text()
    assert 'exec "$QBIN" "$@" -p "$PORT"' in entry
    kdb = BASE['services']['openbq-kdb']
    assert kdb['command'] == ['/opt/openbq-kdb/startup.q']  # REVIEW (2026-10-14): /opt/kdb-ws renamed /opt/openbq-kdb and kdb['environment']['KX_PORT'] == '5000'


def test_the_docs_say_the_default_kdb_image_is_private_amd64_only_and_how_to_build_your_own():
    """D2: kdb+ is proprietary, so the default image is private and never published; readers
    build their own from their licensed KDB-X with compose.kdb-build.yml."""
    for path in ('README.md', 'kdb-x/README.md', 'NOTICE'):
        text = (ROOT / path).read_text()
        assert 'private' in text and 'amd64' in text and 'KDB_IMAGE' in text, path
        assert 'compose.kdb-build.yml' in text, path
        # A floating tag is never named on its own: the digest-pinned ref, or none.
        assert 'kdb-x:amd64`' not in text and 'kdb-x:amd64)' not in text, path
    # The documented build names the real service.
    assert 'build openbq-kdb' in (ROOT / 'kdb-x/README.md').read_text()
