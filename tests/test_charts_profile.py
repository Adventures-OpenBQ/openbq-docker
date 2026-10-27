# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v12 `charts-v12` profile: opt-in, unpublished, and the default stack is unchanged."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = yaml.safe_load((ROOT / 'v12/compose.charts.yaml').read_text())['services']


def test_every_charts_service_is_opt_in_unpublished_and_locked_down():
    assert set(SERVICES) == {'arts-charts', 'arts-charts-worker', 'ntfy'}
    for name, service in SERVICES.items():
        assert service['profiles'] == ['charts-v12'], name
        assert 'ports' not in service, name
        assert service['networks'] == ['openbq-internal'], name
        assert service['read_only'] is True and service['cap_drop'] == ['ALL'], name
        assert 'no-new-privileges:true' in service['security_opt'], name


def test_one_image_runs_both_and_only_the_api_migrates():
    api, worker = SERVICES['arts-charts'], SERVICES['arts-charts-worker']
    assert api['image'] == worker['image'] == 'openbq-arts-charts:12.0.0'
    assert api['command'] == ['uvicorn', '--factory', 'arts_charts.app:create_app', '--host', '0.0.0.0', '--port', '8000']
    assert worker['command'] == ['python', '-m', 'arts_charts.worker']  # waits for the API's migration
    assert worker['environment'] == {'ARTS_CHARTS_API_URL': 'http://arts-charts:8000', 'ARTS_CHARTS_NTFY_URL': 'http://ntfy:2586'}
    for service in (api, worker):
        assert service['volumes'] == ['arts-charts-data:/data']
        assert [e['path'] for e in service['env_file']] == ['${ARTS_CHARTS_STACK_ENV:-./credentials.env}', '${ARTS_CHARTS_ENV:-./v12/charts.env}']
        assert all(e['required'] is True for e in service['env_file'])


def test_ntfy_is_pinned_deny_all_and_has_no_upstream_unless_set():
    ntfy = SERVICES['ntfy']
    assert re.fullmatch(r'binwiederhier/ntfy:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}', ntfy['image'])
    env = ntfy['environment']
    assert env['NTFY_AUTH_DEFAULT_ACCESS'] == 'deny-all' and env['NTFY_ENABLE_SIGNUP'] == 'false'
    assert env['NTFY_UPSTREAM_BASE_URL'] == '${NTFY_UPSTREAM_BASE_URL:-}'
    assert ntfy['volumes'] == ['ntfy-data:/var/lib/ntfy']
    assert 'env_file' not in ntfy  # never sees ARTS_CHARTS_SECRET


def test_the_env_example_lists_every_setting_and_holds_placeholders_only():
    text = (ROOT / 'v12/charts.env.example').read_text()
    for key in ('ARTS_CHARTS_SECRET', 'ARTS_CHARTS_ODP_URL', 'ARTS_CHARTS_LIVE_GRID_URL', 'ARTS_CHARTS_DB',
                'ARTS_CHARTS_TEMPORAL_URL', 'ARTS_CHARTS_TEMPORAL_TOKEN', 'ARTS_CHARTS_TEMPORAL_DATASET',
                'ARTS_CHARTS_DEFAULT_PROVIDER', 'ARTS_CHARTS_RITA_URL', 'ARTS_CHARTS_NTFY_TOPIC',
                'ARTS_CHARTS_NTFY_TOKEN', 'ARTS_CHARTS_PUBLIC_URL', 'ARTS_CHARTS_PUSH_CAP',
                'ARTS_CHARTS_APP_LINK', 'ARTS_CHARTS_ODP_USER', 'NTFY_BASE_URL', 'NTFY_UPSTREAM_BASE_URL'):
        assert key in text, key
    values = dict(l.split('=', 1) for l in text.splitlines() if l and not l.startswith('#'))
    assert values.pop('ARTS_CHARTS_ODP_URL') == 'http://openbq-api:6900'
    assert set(values.values()) == {''}, values


def compose(*args):
    return subprocess.run(['docker', 'compose', '--project-directory', str(ROOT), *args],
                          check=True, capture_output=True, text=True, env=dict(os.environ)).stdout


@pytest.mark.skipif(not shutil.which('docker'), reason='needs docker compose')
def test_with_the_profile_off_the_overlay_changes_nothing():
    base = compose('-f', 'docker-compose.yml', 'config', '--no-env-resolution')
    with_charts = compose('-f', 'docker-compose.yml', '-f', 'v12/compose.charts.yaml', 'config', '--no-env-resolution')
    # compose echoes the overlay's top-level x-arts-charts anchor block; everything else must match
    def strip(text):
        return {k: v for k, v in yaml.safe_load(text).items() if k != 'x-arts-charts'}
    assert strip(with_charts) == strip(base)


@pytest.mark.skipif(not shutil.which('docker'), reason='needs docker compose')
def test_with_the_profile_on_the_config_validates():
    compose('-f', 'docker-compose.yml', '-f', 'v12/compose.charts.yaml', '--profile', 'charts-v12',
            'config', '--quiet', '--no-env-resolution')
