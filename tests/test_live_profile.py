# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v10 `live` profile: kdb and live-grid are opt-in, unpublished, and carry no licence or key."""
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
SERVICES = COMPOSE['services']
LIVE = ('kdb', 'live-grid')


def test_kdb_and_live_grid_start_only_with_the_live_profile():
    for name in LIVE:
        assert SERVICES[name]['profiles'] == ['live'], name
    default = sorted(name for name, service in SERVICES.items() if 'profiles' not in service)
    # The default stack is exactly what it was at v9: the sidecar and the API.
    assert default == ['openbq-api', 'tailscale']
    for name in default:
        assert 'kdb' not in json.dumps(SERVICES[name]) and 'live-grid' not in json.dumps(SERVICES[name]), name


def test_the_gateway_does_not_depend_on_the_live_profile():
    # `--profile web` alone must still start: /grid answers 503 until "liveGrid": true.
    assert SERVICES['funnel-gateway'].get('depends_on') == ['openbq-api']
    settings = json.loads((ROOT / 'funnel-gateway/settings.example.json').read_text())
    assert settings['liveGrid'] is False


def test_nothing_in_the_live_profile_is_published_or_served():
    for name in LIVE:
        assert 'ports' not in SERVICES[name], name
        assert SERVICES[name]['networks'] == ['openbq-internal'], name
    for config in ('serve.json', 'serve-funnel.json', 'serve-v3.json'):
        text = (ROOT / 'ts-config' / config).read_text()
        assert 'kdb' not in text and 'live-grid' not in text and '6903' not in text, config


def test_kdb_uses_the_named_image_and_mounts_the_licence_read_only():
    kdb = SERVICES['kdb']
    assert kdb['image'] == 'ghcr.io/artcashin/kdb-x:amd64'
    assert './kdb-license:/opt/kx-license:ro' in kdb['volumes']
    assert './kdb-license:/opt/kx-license:ro' in SERVICES['live-grid']['volumes']


def test_crash_recovery_is_always_on_kdb_runs_the_repository_scripts_read_only():
    kdb = SERVICES['kdb']
    # No copying by hand: q runs the repo's startup.q, which loads the repo's persist.q.
    assert './kdb-ws/startup.q:/opt/kdb-ws/startup.q:ro' in kdb['volumes']
    assert './kdb-ws/persist.q:/opt/kdb-ws/persist.q:ro' in kdb['volumes']
    assert kdb['command'] == ['/opt/kdb-ws/startup.q']
    assert kdb['environment']['KDB_PERSIST_Q'] == '/opt/kdb-ws/persist.q'
    startup = (ROOT / 'kdb-ws/startup.q').read_text()
    assert 'getenv`KDB_PERSIST_Q' in startup and startup.rstrip().endswith('system"l ",kdbPersistQ;')
    # No bind of the operator's ./kdb-data: nothing has to be put there first.
    assert not any(v.startswith('./kdb-data') for v in kdb['volumes'])


def test_the_tick_logs_live_on_a_named_volume_that_survives_recreation():
    kdb = SERVICES['kdb']
    assert 'kdb-data:/data' in kdb['volumes']
    assert 'kdb-data' in COMPOSE['volumes']
    # persist.q writes its logs under /data, i.e. on that volume
    assert ".tlog.dir:`:/data/logs;" in (ROOT / 'kdb-ws/persist.q').read_text()
    assert 'kdb-data' not in json.dumps({k: v for k, v in SERVICES.items() if k != 'kdb'})


def test_kdb_and_live_grid_restart_themselves():
    for name in LIVE:
        assert SERVICES[name]['restart'] == 'unless-stopped', name
    # q closes its log handle in .z.exit; compose waits for it before SIGKILL.
    assert SERVICES['kdb']['stop_grace_period'] == '30s'


def test_live_grid_reaches_kdb_and_the_api_on_the_bridge_and_never_spawns_q():
    env = SERVICES['live-grid']['environment']
    assert env['KDB_EMBEDDED'] == 'false' and env['KDB_BIND_HOST'] == 'kdb' and env['KDB_PORT'] == '5000'
    assert env['OPENBB_URL'] == 'http://openbq-api:6900'
    assert env['OPENBB_HISTORY_NAMESPACE'] == 'eodhd'
    assert SERVICES['live-grid']['env_file'] == [{'path': './credentials.env', 'required': False}]
    assert SERVICES['live-grid']['build'] == {'context': '.', 'dockerfile': 'live-grid/Dockerfile'}


def test_no_licence_or_key_is_tracked_and_the_examples_are_empty():
    tracked = subprocess.run(['git', 'ls-files', 'kdb-license', 'kdb-data', 'live-grid-data'],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert tracked == ['kdb-license/.gitkeep']
    ignored = subprocess.run(['git', 'check-ignore', 'kdb-license/kc.lic', 'kdb-data/startup.q',
                              'live-grid-data/watchlist.json'], cwd=ROOT, capture_output=True, text=True)
    assert ignored.stdout.split() == ['kdb-license/kc.lic', 'kdb-data/startup.q', 'live-grid-data/watchlist.json']
    env = dict(line.split('=', 1) for line in (ROOT / 'credentials.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    assert env['EODHD_API_KEY'] == '' and env['LIVE_GRID_PUBLIC_URL'] == ''
    smoke = (ROOT / 'live-grid/scripts/smoke.py').read_text()
    assert 'os.environ.get("EODHD_DEMO_WS_KEY", "")' in smoke
