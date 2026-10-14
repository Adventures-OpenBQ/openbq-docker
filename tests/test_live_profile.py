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
LIVE = ('openbq-kdb', 'live-grid')  # REVIEW (2026-10-14): the kdb service is openbq-kdb


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
    # REVIEW (user ruling 2026-10-14: the kdb tier is openbq-kdb, vendored in v10/kdb/source): the service
    # is renamed kdb -> openbq-kdb and kdb-ws/ is the vendored q/; the same facts are asserted.
    kdb = SERVICES['openbq-kdb']
    assert kdb['image'] == 'ghcr.io/artcashin/kdb-x:amd64'
    assert '${KDB_LICENSE_DIR:-./kdb-license}:/opt/kx-license:ro' in kdb['volumes']
    assert '${KDB_LICENSE_DIR:-./kdb-license}:/opt/kx-license:ro' in SERVICES['live-grid']['volumes']


def test_crash_recovery_is_always_on_kdb_runs_the_repository_scripts_read_only():
    # REVIEW (user ruling 2026-10-14: the kdb tier is openbq-kdb, vendored in v10/kdb/source): the service
    # is renamed kdb -> openbq-kdb and kdb-ws/ is the vendored q/; the same facts are asserted.
    kdb = SERVICES['openbq-kdb']
    # No copying by hand: q runs the repo's startup.q, which loads the repo's persist.q.
    assert './v10/kdb/source/q/startup.q:/opt/openbq-kdb/startup.q:ro' in kdb['volumes']
    assert './v10/kdb/source/q/persist.q:/opt/openbq-kdb/persist.q:ro' in kdb['volumes']
    assert kdb['command'] == ['/opt/openbq-kdb/startup.q']
    assert kdb['environment']['KDB_PERSIST_Q'] == '/opt/openbq-kdb/persist.q'
    startup = (ROOT / 'v10/kdb/source/q/startup.q').read_text()
    assert 'getenv`KDB_PERSIST_Q' in startup and startup.rstrip().endswith('system"l ",kdbPersistQ;')
    # No bind of the operator's ./kdb-data: nothing has to be put there first.
    assert not any(v.startswith('./kdb-data') for v in kdb['volumes'])


def test_the_tick_logs_live_on_a_named_volume_that_survives_recreation():
    # REVIEW (user ruling 2026-10-14: the kdb tier is openbq-kdb, vendored in v10/kdb/source): the service
    # is renamed kdb -> openbq-kdb and kdb-ws/ is the vendored q/; the same facts are asserted.
    kdb = SERVICES['openbq-kdb']
    assert 'kdb-data:/data' in kdb['volumes']
    assert 'kdb-data' in COMPOSE['volumes']
    # persist.q writes its logs under /data, i.e. on that volume
    assert ".tlog.dir:`:/data/logs;" in (ROOT / 'v10/kdb/source/q/persist.q').read_text()
    assert 'kdb-data' not in json.dumps({k: v for k, v in SERVICES.items() if k != 'openbq-kdb'})


def test_kdb_and_live_grid_restart_themselves():
    for name in LIVE:
        assert SERVICES[name]['restart'] == 'unless-stopped', name
    # q closes its log handle in .z.exit; compose waits for it before SIGKILL.
    assert SERVICES['openbq-kdb']['stop_grace_period'] == '30s'


def test_live_grid_reaches_kdb_and_the_api_on_the_bridge_and_never_spawns_q():
    env = SERVICES['live-grid']['environment']
    assert env['KDB_EMBEDDED'] == 'false' and env['KDB_BIND_HOST'] == 'openbq-kdb' and env['KDB_PORT'] == '5000'
    assert env['OPENBB_URL'] == 'http://openbq-api:6900'
    assert env['OPENBB_HISTORY_NAMESPACE'] == 'eodhd'
    # v10 S3 tier: rustfs.env (DELTA_S3_*) joins credentials.env, both optional.
    assert SERVICES['live-grid']['env_file'] == [{'path': './credentials.env', 'required': False},
                                                 {'path': './rustfs.env', 'required': False}]
    assert SERVICES['live-grid']['build'] == {'context': '.', 'dockerfile': 'live-grid/Dockerfile'}


def test_the_tick_spool_is_on_the_persistent_live_grid_volume_and_bounded():
    """User ruling 2026-10-12: ticks are spooled to the filesystem and survive restarts."""
    lg = SERVICES['live-grid']
    env = lg['environment']
    assert 'live-grid-data:/data' in lg['volumes']
    assert 'live-grid-data' in COMPOSE['volumes']
    assert env['LIVE_GRID_SPOOL_DIR'] == '/data/spool'  # on the named volume, not the container layer
    assert int(env['LIVE_GRID_SPOOL_MAX_MB']) > 0
    assert float(env['LIVE_GRID_SPOOL_FSYNC_S']) > 0
    assert (float(env['KDB_RETRY_INITIAL_S']), float(env['KDB_RETRY_MAX_S'])) == (1.0, 15.0)


def test_the_subscriptions_widget_is_published_for_the_gateway_to_reframe():
    """V10-P5 (user, 2026-10-13): live-grid publishes its Subscriptions widget only with an
    absolute LIVE_GRID_PUBLIC_URL. The gateway rewrites the endpoint to its own
    /grid/subscriptions, so the compose default is live-grid's internal address -- present,
    overridable from .env, and never a host port (P3 still holds; see the test above)."""
    env = SERVICES['live-grid']['environment']
    assert env['LIVE_GRID_PUBLIC_URL'] == '${LIVE_GRID_PUBLIC_URL:-http://live-grid:6903}'


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


def test_one_licence_directory_reaches_every_service_that_needs_it():
    # REVIEW (user, 2026-10-12: the kdb licence lives in bdobb-dev/openbb-kdb): the mount
    # source is overridable as KDB_LICENSE_DIR, default ./kdb-license; still read-only.
    mount = '${KDB_LICENSE_DIR:-./kdb-license}:/opt/kx-license:ro'
    users = sorted(k for k, v in SERVICES.items() if any('kx-license' in str(m) for m in v.get('volumes', [])))
    assert users == ['eod-dump', 'live-grid', 'openbq-kdb']  # REVIEW (2026-10-14): kdb renamed openbq-kdb; sorted
    assert all(mount in SERVICES[k]['volumes'] for k in users)
