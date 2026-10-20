# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v10 S3 tier (user rulings 2026-10-12): RustFS, the bucket init and eod-dump, in the
opt-in `live` profile only, unpublished, with no MinIO software and no committed secret."""
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
SERVICES = COMPOSE['services']
TIER = ('rustfs', 'rustfs-init', 'eod-dump')


def _env(path):
    return dict(line.split('=', 1) for line in (ROOT / path).read_text().splitlines()
                if line and not line.startswith('#'))


def test_the_tier_starts_only_with_the_live_profile_and_the_default_stack_is_unchanged():
    for name in TIER:
        assert SERVICES[name]['profiles'] == ['live'], name
    default = sorted(name for name, service in SERVICES.items() if 'profiles' not in service)
    assert default == ['openbq-api', 'tailscale']
    text = json.dumps({name: SERVICES[name] for name in default})
    for word in ('rustfs', 'eod', 'DELTA_', 'lake'):
        assert word not in text, word
    # openbq-api's image is untouched: the lake image is its own Dockerfile.
    # The base compose builds the full API image, the Dockerfile's `v3` stage.
    assert SERVICES['openbq-api']['build'] == {'context': '.', 'target': 'v3'}
    assert SERVICES['openbq-api']['image'] == 'openbq-local:10.0.0'


def test_no_minio_or_mc_image_binary_service_or_volume_is_left():
    text = (ROOT / 'docker-compose.yml').read_text().lower()
    assert 'minio' not in text
    assert not re.search(r'(^|[\s"\[/])mc(\s|"|$)', text, re.M)
    for name, service in SERVICES.items():
        assert 'minio' not in name and 'minio' not in str(service.get('image', '')), name
    assert not any('minio' in v for v in COMPOSE['volumes'])
    assert not (ROOT / 'minio').exists() and not (ROOT / 'minio.env.example').exists()
    for path in ('Dockerfile.lake', 'scripts/s3_init.py'):
        assert 'minio/mc' not in (ROOT / path).read_text().lower()


def test_rustfs_is_the_upstream_image_pinned_to_a_released_version_and_digest():
    image = SERVICES['rustfs']['image']
    assert re.fullmatch(r'rustfs/rustfs:1\.0\.1@sha256:[0-9a-f]{64}', image), image
    assert 'build' not in SERVICES['rustfs']


def test_nothing_in_the_tier_is_published_or_served():
    for name in TIER:
        assert 'ports' not in SERVICES[name], name
        # D1: the store and its jobs are on the internal live-private network only.
        assert SERVICES[name]['networks'] == ['live-private'], name
        assert 'network_mode' not in SERVICES[name], name
    env = SERVICES['rustfs']['environment']
    assert env['RUSTFS_CONSOLE_ENABLE'] == 'false'
    for config in ('serve.json', 'serve-funnel.json', 'serve-v3.json', 'serve-v6.json', 'serve-v6-keys.json'):
        text = (ROOT / 'ts-config' / config).read_text()
        assert 'rustfs' not in text and '9000' not in text and '9001' not in text, config


def test_rustfs_fails_closed_on_an_empty_or_default_root_pair():
    rustfs = SERVICES['rustfs']
    script = rustfs['command'][0]
    assert rustfs['entrypoint'] == ['/bin/sh', '-ec']
    assert ':*|*:|rustfsadmin:*|*:rustfsadmin)' in script
    # D22 (2026-10-16): the refusal idles instead of exiting, so unless-stopped does not turn it
    # into a restart loop logging every second; the health check stays failing, and the store
    # never starts. SIGTERM still ends it at once.
    refusal = script.split('rustfsadmin)', 1)[1].split('esac', 1)[0]
    assert 'exit 1 ;;' not in refusal and "trap 'exit 1' TERM INT" in refusal
    assert 'while :; do sleep 3600 & wait $$!; done ;;' in refusal  # $$: compose's escape for $
    assert script.rstrip().endswith('exec /entrypoint.sh rustfs')
    assert rustfs['healthcheck']['test'] == ['CMD', 'curl', '-fsS', 'http://127.0.0.1:9000/health']
    assert rustfs['restart'] == 'unless-stopped'
    # REVIEW (user ruling 2026-10-12, "rustfs should be persistent"): the store moved from the
    # named volume rustfs-data to a host directory, so `down -v` cannot delete it.
    assert rustfs['volumes'] == ['${RUSTFS_DATA_DIR:-./rustfs-data}:/data']
    assert 'rustfs-data' not in COMPOSE['volumes']


def test_rustfs_data_is_a_host_directory_made_writable_before_rustfs_starts():
    rustfs, perms = SERVICES['rustfs'], SERVICES['rustfs-perms']
    # Same directory in both, and rustfs waits for the one-shot to finish.
    assert perms['volumes'] == rustfs['volumes'] == ['${RUSTFS_DATA_DIR:-./rustfs-data}:/data']
    assert rustfs['depends_on'] == {'rustfs-perms': {'condition': 'service_completed_successfully'}}
    assert perms['profiles'] == ['live'] and perms['restart'] == 'no'
    # The RustFS image runs as 10001:10001; only the one-shot runs as root, with no network.
    assert perms['user'] == '0:0' and perms['network_mode'] == 'none'
    script = perms['command'][0]
    assert 'chown -R 10001:10001 /data' in script and 'stat -c %u:%g /data' in script
    # It reuses the lake image rather than pulling another one.
    assert perms['image'] == SERVICES['rustfs-init']['image'] == 'openbq-lake:10.0.0'
    # No other service sees the store's files.
    others = {k: v for k, v in SERVICES.items() if k not in ('rustfs', 'rustfs-perms')}
    assert 'RUSTFS_DATA_DIR' not in json.dumps(others) and 'rustfs-data' not in json.dumps(others)


def test_the_bucket_is_made_over_the_s3_api_before_the_flush_starts():
    init, eod = SERVICES['rustfs-init'], SERVICES['eod-dump']
    assert init['command'] == ['python', '/opt/s3_init.py'] and init['restart'] == 'no'
    assert init['depends_on'] == {'rustfs': {'condition': 'service_healthy'}}
    assert eod['depends_on'] == {'rustfs-init': {'condition': 'service_completed_successfully'}}
    for svc in (init, eod):
        assert svc['image'] == 'openbq-lake:10.0.0'
        assert svc['build'] == {'context': '.', 'dockerfile': 'Dockerfile.lake'}
    assert eod['entrypoint'] == ['python', '/opt/eod_dump.py', '--loop']
    # REVIEW (2026-10-14): the kdb service is openbq-kdb, so eod-dump dials that host.
    assert eod['environment']['KDB_HOST'] == 'openbq-kdb' and eod['restart'] == 'unless-stopped'
    # Q2 (re-review 2026-10-16): eod-dump is on live-private with no egress, so a kc.lic that calls
    # KX's licence daemon would fail every flush. It needs IPC and conversions only, which PyKX
    # does unlicensed, so it carries no licence at all.
    assert eod['environment']['PYKX_UNLICENSED'] == 'true'
    assert 'QLIC' not in eod['environment'] and 'volumes' not in eod


def test_the_lake_image_keeps_openbb_platform_5():
    text = (ROOT / 'Dockerfile.lake').read_text()
    assert '--constraint /tmp/requirements.lock' in text and 'openbb-core==2.0.1' in text
    assert 'openbb-core==2.0.1' in (ROOT / 'requirements.lock').read_text()
    assert 'COPY scripts/eod_dump.py scripts/s3_init.py /opt/' in text


def test_live_grid_reads_flushed_days_back_from_the_same_store():
    lg = SERVICES['live-grid']
    assert {'path': './rustfs.env', 'required': False} in lg['env_file']
    assert lg['environment']['LIVE_GRID_LAKE_READBACK'] == 'true'
    assert lg['environment']['LIVE_GRID_LAKE_LIBRARY'] == _env('eod.env.example')['EOD_LIBRARY'] == 'ticks_live'


def test_env_examples_carry_no_secret_and_the_client_contract_is_path_style_http():
    rustfs = _env('rustfs.env.example')
    for key in ('RUSTFS_ACCESS_KEY', 'RUSTFS_SECRET_KEY', 'DELTA_S3_ACCESS', 'DELTA_S3_SECRET'):
        assert rustfs[key] == '', key
    assert rustfs['DELTA_S3_ENDPOINT'] == 'rustfs' and rustfs['DELTA_S3_PORT'] == '9000'
    assert rustfs['DELTA_S3_SECURE'] == 'false'
    assert _env('eod.env.example')['EOD_HOT_SESSIONS'] == '0'
    for service in TIER:
        for entry in SERVICES[service].get('env_file', []):
            assert entry['required'] is False, (service, entry)


def test_store_data_and_credentials_are_never_tracked():
    ignored = subprocess.run(['git', 'check-ignore', 'rustfs.env', 'eod.env', 'rustfs-data/x', 'minio-data/x'],
                             cwd=ROOT, capture_output=True, text=True)
    assert ignored.stdout.split() == ['rustfs.env', 'eod.env', 'rustfs-data/x', 'minio-data/x']
    tracked = subprocess.run(['git', 'ls-files', 'rustfs.env', 'eod.env', 'rustfs-data', 'minio-data'],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert tracked == []
