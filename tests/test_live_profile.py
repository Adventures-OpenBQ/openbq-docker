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
    # D1: q is on live-private only; live-grid also keeps openbq-internal for the gateway and the API.
    assert SERVICES['openbq-kdb']['networks'] == ['live-private']
    assert SERVICES['live-grid']['networks'] == ['openbq-internal', 'live-private']
    for config in ('serve.json', 'serve-funnel.json', 'serve-v3.json', 'serve-v6.json', 'serve-v6-keys.json'):
        text = (ROOT / 'ts-config' / config).read_text()
        assert 'kdb' not in text and 'live-grid' not in text and '6903' not in text, config


def test_kdb_uses_the_named_image_and_mounts_the_licence_read_only():
    # REVIEW (user ruling 2026-10-14: the kdb tier is openbq-kdb, vendored in v10/kdb/source): the service
    # is renamed kdb -> openbq-kdb and kdb-ws/ is the vendored q/; the same facts are asserted.
    kdb = SERVICES['openbq-kdb']
    # D2: a private amd64-only image, pinned by digest, overridable as KDB_IMAGE.
    assert kdb['image'] == '${KDB_IMAGE:-ghcr.io/artcashin/kdb-x:amd64@sha256:013490f90a166e0863651f2c8a7f5d24e8d1beec68d2e3e541c1a2281653a77c}'
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
    # v10 S3 tier: rustfs.env (DELTA_S3_*) joins credentials.env, both optional; the committed
    # public demo keys (credentials.demo.env) load first, so credentials.env overrides them.
    assert SERVICES['live-grid']['env_file'] == [{'path': './credentials.demo.env', 'required': True},
                                                 {'path': './credentials.env', 'required': False},
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


def test_live_grid_does_not_advertise_its_internal_hostname():
    """V10-P5 (user, 2026-10-13) made the default http://live-grid:6903, which no client can
    load: a direct connection (tailnet Serve, a local relay) framed a blank page. Empty now,
    live-grid names the page by the address the request used; the gateway still rewrites the
    endpoint to its own /grid/subscriptions. Overridable from .env, never a host port (P3)."""
    env = SERVICES['live-grid']['environment']
    assert env['LIVE_GRID_PUBLIC_URL'] == '${LIVE_GRID_PUBLIC_URL:-}'
    assert 'live-grid:6903' not in json.dumps(env)


def test_no_licence_or_key_is_tracked_and_the_examples_are_empty():
    tracked = subprocess.run(['git', 'ls-files', 'kdb-license', 'kdb-data', 'live-grid-data'],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert tracked == ['kdb-license/.gitkeep']
    ignored = subprocess.run(['git', 'check-ignore', 'kdb-license/kc.lic', 'kdb-data/startup.q',
                              'live-grid-data/watchlist.json'], cwd=ROOT, capture_output=True, text=True)
    assert ignored.stdout.split() == ['kdb-license/kc.lic', 'kdb-data/startup.q', 'live-grid-data/watchlist.json']
    env = dict(line.split('=', 1) for line in (ROOT / 'credentials.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    # EODHD_API_KEY is commented out so credentials.demo.env's public "demo" token applies.
    assert 'EODHD_API_KEY' not in env and '# EODHD_API_KEY=' in (ROOT / 'credentials.env.example').read_text()
    assert env['LIVE_GRID_PUBLIC_URL'] == ''
    smoke = (ROOT / 'live-grid/scripts/smoke.py').read_text()
    assert 'os.environ.get("EODHD_DEMO_WS_KEY", "")' in smoke


def test_one_licence_directory_reaches_every_service_that_needs_it():
    # REVIEW (user, 2026-10-12: the kdb licence lives in bdobb-dev/openbb-kdb): the mount
    # source is overridable as KDB_LICENSE_DIR, default ./kdb-license; still read-only.
    mount = '${KDB_LICENSE_DIR:-./kdb-license}:/opt/kx-license:ro'
    users = sorted(k for k, v in SERVICES.items() if any('kx-license' in str(m) for m in v.get('volumes', [])))
    # Q2 (re-review 2026-10-16): eod-dump left the list -- it only speaks IPC, with PyKX unlicensed.
    assert users == ['live-grid', 'openbq-kdb']  # REVIEW (2026-10-14): kdb renamed openbq-kdb; sorted
    assert all(mount in SERVICES[k]['volumes'] for k in users)


def test_q_and_the_store_are_on_an_internal_network_only_live_grid_and_the_lake_jobs_join():
    """D1 (2026-10-16): q's IPC runs any q code and RustFS holds the root pair, so neither
    may share a bridge with the internet-facing gateway or with openbq-api. They sit on
    live-private (internal: no egress, no other peer); live-grid joins it and keeps
    openbq-internal, so funnel-gateway still reaches live-grid."""
    assert COMPOSE['networks']['live-private'] == {'internal': True}
    private = {'openbq-kdb', 'rustfs', 'rustfs-init', 'eod-dump'}
    for name in private:
        assert SERVICES[name]['networks'] == ['live-private'], name
    members = {k for k, v in SERVICES.items() if 'live-private' in v.get('networks', [])}
    assert members == private | {'live-grid'}
    # The gateway and the API cannot reach q's port or RustFS: no network in common.
    for outsider in ('funnel-gateway', 'openbq-api', 'tailscale', 'rss-ticker', 'table-service'):
        nets = set(SERVICES[outsider]['networks'])
        for name in private:
            assert not nets & set(SERVICES[name]['networks']), (outsider, name)
    # ...but it can reach live-grid.
    assert set(SERVICES['funnel-gateway']['networks']) & set(SERVICES['live-grid']['networks'])
    # The overlays attach nothing to live-private either.
    for overlay in ('docker-compose.v3.yml', 'docker-compose.v6.yml'):
        assert 'live-private' not in (ROOT / overlay).read_text(), overlay


def test_the_default_stack_keeps_its_v9_networks():
    """D1: the default services are untouched; openbq-internal is still a plain bridge."""
    assert COMPOSE['networks']['openbq-internal'] == {'driver': 'bridge'}
    assert SERVICES['tailscale']['networks'] == SERVICES['openbq-api']['networks'] == ['openbq-internal']


def test_env_example_sets_nothing_and_names_no_home_directory():
    """D9 (2026-10-16): `cp .env.example .env` must leave every compose default in force, so
    the licence mount stays ./kdb-license; the example is commented and generic."""
    text = (ROOT / '.env.example').read_text()
    assigned = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    assert assigned == []
    assert '# KDB_LICENSE_DIR=./kdb-license' in text.splitlines()
    for path in ('.env.example', 'README.md', 'docs/v10/live-grid-kdb-port.md'):
        body = (ROOT / path).read_text()
        assert '~/Developer' not in body and "maintainer's licence" not in body, path


def test_the_live_grid_image_does_not_carry_the_q_demo_chart():
    """D19 (2026-10-16): live-chart.html takes any ?ws= URL and writes feed data into innerHTML
    unescaped, on live-grid's origin, and loads a CDN script with no integrity hash. Nothing on
    this stack can reach it (no host port, no /grid route), so it stays out of the image."""
    copies = [line for line in (ROOT / 'live-grid/Dockerfile').read_text().splitlines()
              if line.startswith(('COPY', 'ADD'))]
    assert copies and not any('live-chart' in line for line in copies)


def test_live_grid_is_pinned_and_runs_unprivileged():
    """D21 (2026-10-16): the base by digest, plotly by checksum, `pip check`, a non-root user
    that owns /data (so a new named volume inherits it), and compose's read-only root."""
    import re

    dockerfile = (ROOT / 'live-grid/Dockerfile').read_text()
    assert re.search(r'^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$', dockerfile, re.M)
    assert re.search(r'^ADD --checksum=sha256:[0-9a-f]{64} https://cdn\.plot\.ly/plotly-2\.35\.2\.min\.js ', dockerfile, re.M)
    assert 'pip check' in dockerfile
    assert 'install -d -o 10001 -g 10001 /data' in dockerfile and '\nUSER 10001:10001\n' in dockerfile
    lg = SERVICES['live-grid']
    assert lg['read_only'] is True and lg['cap_drop'] == ['ALL']
    assert lg['security_opt'] == ['no-new-privileges:true']
    assert any(t.startswith('/tmp:') for t in lg['tmpfs'])
    assert 'version = "10.0.0"' in (ROOT / 'live-grid/pyproject.toml').read_text()
    assert re.search(r'^FROM debian:bookworm-slim@sha256:[0-9a-f]{64}$', (ROOT / 'kdb-x/Dockerfile').read_text(), re.M)


def test_a_one_shot_job_gives_live_grid_data_to_its_uid_before_live_grid_starts():
    """Q1 (re-review 2026-10-16): a live-grid-data volume made by the earlier root-run image is
    owned by root, and live-grid (uid 10001, cap_drop ALL) can neither write nor chown it.
    live-grid-perms, like rustfs-perms, fixes ownership as root with no network first."""
    perms, lg = SERVICES['live-grid-perms'], SERVICES['live-grid']
    assert perms['profiles'] == ['live'] and perms['restart'] == 'no'
    assert perms['user'] == '0:0' and perms['network_mode'] == 'none'
    assert perms['image'] == lg['image'] and perms['build'] == lg['build']
    assert perms['volumes'] == ['live-grid-data:/data']
    script = perms['command'][0]
    assert perms['entrypoint'] == ['/bin/sh', '-ec']
    assert 'chown 10001:10001' in script and '! -user 10001' in script
    assert 'cap_drop' not in perms  # chown needs CAP_CHOWN
    assert lg['depends_on'] == {'live-grid-perms': {'condition': 'service_completed_successfully'}}
    readme = (ROOT / 'live-grid/README.md').read_text()
    assert 'live-grid-perms' in readme and 'run --rm --user 0 live-grid chown' not in readme


def test_matplotlib_keeps_its_config_on_the_tmp_tmpfs():
    """L2 (NAS, 2026-10-16): the eodhd SDK pulls in matplotlib, whose default config dir
    (/.config/matplotlib for uid 10001) is on the read-only root, so it warned on every start
    and fell back to a fresh temporary cache. The image points it at the /tmp tmpfs that
    compose gives live-grid."""
    dockerfile = (ROOT / 'live-grid/Dockerfile').read_text()
    assert 'MPLCONFIGDIR=/tmp/matplotlib' in dockerfile
    assert any(t.startswith('/tmp:') for t in SERVICES['live-grid']['tmpfs'])
