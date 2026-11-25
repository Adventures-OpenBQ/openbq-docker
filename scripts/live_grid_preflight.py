#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Release-pinned, project-scoped live-grid gate for setup and deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class PreflightError(RuntimeError):
    pass


PROBE = '''import base64,json,os,urllib.request
h={}
if os.getenv('OPENBB_API_AUTH','').strip().lower() in ('1','true','yes','on'):
 p=os.environ.get('OPENBB_API_USERNAME','')+':'+os.environ.get('OPENBB_API_PASSWORD','')
 h['Authorization']='Basic '+base64.b64encode(p.encode()).decode()
for path in ('/health','/widgets.json'):
 with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:6903'+path,headers=h),timeout=5) as r:
  assert r.status==200
  body=json.load(r)
  if path=='/health': assert body.get('status')=='ok'
  if path=='/widgets.json':
   assert 'live_grid' in body and 'day_chart' in body
   if CHECK_CHART_STREAM:
    assert body.get('live_chart',{}).get('extra_metadata',{}).get('chart_stream_v1') is True
'''


def release_image(release, override, pins=ROOT/'live-grid/runtime-images.json'):
    match = re.fullmatch(r'v?(\d+)(?:\.\d+){0,2}(?:-[a-zA-Z0-9.-]+)?', release)
    if not match:
        raise PreflightError('Invalid release version')
    major = int(match[1])
    if major < 10:
        return None
    image = override or json.loads(Path(pins).read_text()).get(str(major))
    if not image:
        raise PreflightError('This release needs its own live-grid image pin; supply --image DIGEST')
    if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}', image):
        raise PreflightError('live-grid image must be pinned with @sha256: and a full digest')
    return image


def ensure(docker, compose, image, *, timeout=90, check_only=False, require_chart_stream=False):
    if not check_only:
        docker(['pull', image])
    expected = docker(['image', 'inspect', image, '--format', '{{.Id}}']).strip()
    if not expected:
        raise PreflightError('Expected live-grid image is unavailable')

    def inspect():
        ids = docker([*compose, 'ps', '-a', '-q', 'live-grid']).split()
        if len(ids) > 1:
            raise PreflightError('Expected one live-grid container in the selected project')
        if not ids:
            return None, None
        return ids[0], json.loads(docker(['inspect', ids[0]]))[0]

    cid, state = inspect()
    stale = (not state or state['Image'] != expected or state['State']['Status'] != 'running'
             or state['State'].get('Health', {}).get('Status') == 'unhealthy')
    if stale:
        if check_only:
            raise PreflightError('live-grid is missing, stopped, unhealthy or on the wrong image')
        if 'live-grid-perms' in docker([*compose, 'config', '--services']).split():
            docker([*compose, 'run', '--rm', '--no-deps', '--pull', 'never', 'live-grid-perms'])
        docker([*compose, 'up', '-d', '--no-build', '--pull', 'never', '--no-deps',
                '--force-recreate', 'live-grid'])
    deadline = time.monotonic() + timeout
    while True:
        try:
            cid, state = inspect()
            if not state or state['Image'] != expected or state['State']['Status'] != 'running':
                raise PreflightError('live-grid is not running the expected image')
            health = state['State'].get('Health', {}).get('Status')
            if health and health != 'healthy':
                raise PreflightError('live-grid has not reached healthy status')
            docker(['exec', cid, 'python', '-c', PROBE.replace('CHECK_CHART_STREAM', str(require_chart_stream))])
            return cid
        except PreflightError:
            if time.monotonic() >= deadline:
                raise PreflightError('live-grid readiness failed: inspect the selected service and its API/kdb dependencies') from None
            time.sleep(min(2, max(0, deadline-time.monotonic())))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', required=True)
    p.add_argument('--image', help='Exact image digest for this release; overrides the release manifest')
    p.add_argument('--context')
    p.add_argument('--directory', type=Path, default=Path.cwd())
    p.add_argument('--file', action='append', default=[])
    p.add_argument('--project-name')
    p.add_argument('--env-file', action='append', default=[])
    p.add_argument('--timeout', type=float, default=90)
    p.add_argument('--check-only', action='store_true')
    p.add_argument('--require-chart-stream', action='store_true', help='Also require qualified kdb accepted-stream capability')
    p.add_argument('--deploy', action='store_true', help='Continue with Compose up only after the preflight passes')
    a = p.parse_args(argv)
    if a.timeout < 0 or a.timeout > 600:
        p.error('--timeout must be between 0 and 600 seconds')
    if a.deploy and a.check_only:
        p.error('--deploy and --check-only cannot be combined')
    prefix = ['docker', *(['--context', a.context] if a.context else [])]
    compose = ['compose', '--project-directory', str(a.directory.resolve())]
    if a.project_name:
        compose += ['--project-name', a.project_name]
    for file in a.env_file:
        compose += ['--env-file', file]
    for file in a.file or ['docker-compose.yml']:
        compose += ['--file', str((a.directory/file).resolve())]

    def docker(args):
        try:
            r = subprocess.run([*prefix, *args], capture_output=True, text=True,
                               timeout=max(30, a.timeout+30), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PreflightError('Docker unavailable or command deadline exceeded') from None
        if r.returncode:
            # Compose and upstream errors can include secrets. Keep those out of receipts.
            raise PreflightError('Docker operation failed; check registry authorization, Compose configuration and dependencies')
        return r.stdout

    try:
        image = release_image(a.release, a.image)
        with tempfile.TemporaryDirectory(prefix='openbq-live-grid-') as temp:
            if image:
                compose += ['--profile', 'live']
                services = docker([*compose, 'config', '--services']).split()
                if 'live-grid' not in services:
                    raise PreflightError('Selected Compose configuration has no live-grid service')
                entries = {'live-grid': {'image':image}}
                if 'live-grid-perms' in services:
                    entries['live-grid-perms'] = {'image':image}
                content = json.dumps({'services': entries}, sort_keys=True)
                identity = hashlib.sha256(content.encode()).hexdigest()
                overlay = Path(temp)/'image.json' if a.check_only else a.directory.resolve()/'.openbq'/('live-grid-image-'+identity+'.json')
                overlay.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with overlay.open('x') as f:
                        f.write(content)
                    overlay.chmod(0o600)
                except FileExistsError:
                    if overlay.read_text() != content:
                        raise PreflightError('Retained image override was modified; refusing deployment')
                compose += ['--file', str(overlay)]
                ensure(docker, compose, image, timeout=a.timeout, check_only=a.check_only, require_chart_stream=a.require_chart_stream)
                print('PASS live-grid: expected image and application readiness' + ('; accepted chart capability verified' if a.require_chart_stream else ''))
            else:
                print('SKIP live-grid: release is older than v10')
            if a.deploy:
                docker([*compose, 'up', '-d', '--no-build'])
                if image:
                    ensure(docker, compose, image, timeout=a.timeout, check_only=True, require_chart_stream=a.require_chart_stream)
                print('PASS deployment completed after preflight')
        return 0
    except (PreflightError, ValueError, OSError) as e:
        print('BLOCKED:', str(e))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
