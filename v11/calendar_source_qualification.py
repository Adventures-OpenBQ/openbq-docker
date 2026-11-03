# SPDX-License-Identifier: Apache-2.0
"""Offline installed-calendar qualification, not TemporalDB capture/acceptance.

Run from this checkout with an immutable provider image ID and a NEW output path.
The Docker child has no network and reads only the expected calendar sources.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 16 * 1024 * 1024
NAME = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def write_evidence(destination, report, responses):
    if len(responses) > 32 or any(not NAME.fullmatch(name) for name in responses):
        raise ValueError('bounded basename response identities required')
    if any(not isinstance(raw, bytes) or len(raw) > MAX_BODY for raw in responses.values()):
        raise ValueError('bounded response bytes required')
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    (root/'responses').mkdir()
    body = encoded(report)
    (root/'report.json').write_bytes(body)
    manifest = {'artifact_version':1, 'report_sha256':sha256(body).hexdigest(), 'responses':[]}
    for name, raw in sorted(responses.items()):
        path = 'responses/' + name + '.json'
        (root/path).write_bytes(raw)
        manifest['responses'].append({'path':path, 'bytes':len(raw), 'sha256':sha256(raw).hexdigest()})
    (root/'manifest.json').write_bytes(encoded(manifest))
    return manifest


def verify_evidence(destination):
    """Local integrity only, not signature, source authority or storage durability."""
    root = Path(destination).resolve()
    manifest_path = root/'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 65536:
        raise ValueError('invalid evidence manifest file')
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('artifact_version') != 1 or len(manifest.get('responses', [])) > 32:
        raise ValueError('unsupported evidence manifest')
    report_path = root/'report.json'
    if report_path.is_symlink() or report_path.stat().st_size > 1048576 or sha256(report_path.read_bytes()).hexdigest() != manifest['report_sha256']:
        raise ValueError('report integrity failure')
    seen = set()
    for item in manifest['responses']:
        match = re.fullmatch(r'responses/([A-Za-z0-9_-]{1,80})\.json', item['path'])
        if not match or item['path'] in seen:
            raise ValueError('invalid response path')
        seen.add(item['path'])
        path = root/item['path']
        if path.is_symlink() or path.resolve().parent != root/'responses':
            raise ValueError('response escaped evidence directory')
        if path.stat().st_size > MAX_BODY:
            raise ValueError('response exceeds evidence byte limit')
        raw = path.read_bytes()
        if len(raw) > MAX_BODY or len(raw) != item['bytes'] or sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('response integrity failure')
    return json.loads(report_path.read_bytes())


def inside():
    """Exercise installed packages, never shadow them with mounted source imports."""
    from importlib.metadata import version
    from types import SimpleNamespace
    import openbq_calendar
    from openbq_calendar.canonical import bundle_digest
    from openbq_calendar.contracts import validate_bundle
    from openbq_calendar.registry import CALENDARS
    import openbq_routes.calendar_v1 as route
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    checks, responses, observations, requests = [], {}, {}, []
    def check(name, fn):
        try:
            fn()
            checks.append({'name':name,'status':'pass'})
        except Exception as error:
            checks.append({'name':name,'status':'fail','error':str(error)[:512]})
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    def tree(root):
        return {str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob('*.py'))}
    expected = tree(Path('/expected/calendar'))
    installed = tree(Path(openbq_calendar.__file__).parent)
    check('installed_calendar_source_matches_checkout', lambda: require(
        expected == installed, 'installed calendar source differs from checkout'))
    check('installed_route_source_matches_checkout', lambda: require(
        Path(route.__file__).read_bytes() == Path('/expected/calendar_v1.py').read_bytes(),
        'installed route differs from checkout'))
    app = FastAPI()
    router = SimpleNamespace(api_router=APIRouter())
    route.register(router)
    app.include_router(router.api_router, prefix='/api/v1/calendar')
    client = TestClient(app)
    path = '/api/v1/calendar/trading/v1/bundle'
    def ask(name, calendar, start, end, status=200):
        response = client.get(path, params={'calendar_id':calendar,'start':start,'end':end})
        responses[name] = response.content
        requests.append({'name':name,'method':'GET','path':path,
                         'parameters':{'calendar_id':calendar,'start':start,'end':end},
                         'status_code':response.status_code,
                         'observed_at':datetime.now(timezone.utc).isoformat()})
        require(response.status_code == status, f'{name}: HTTP {response.status_code}, expected {status}')
        return response.json()
    def capabilities():
        response = client.get('/api/v1/calendar/trading/v1/calendars')
        responses['capabilities'] = response.content
        requests.append({'name':'capabilities','method':'GET','path':'/api/v1/calendar/trading/v1/calendars',
                         'parameters':{},'status_code':response.status_code,
                         'observed_at':datetime.now(timezone.utc).isoformat()})
        require(response.status_code == 200, 'capability route failed')
        body = response.json()
        require({c['calendarId'] for c in body['calendars']} == {'exchange:'+c for c in CALENDARS}, 'catalogue mismatch')
        observations['calendar_count'] = len(body['calendars'])
    check('installed_capabilities_match_catalogue', capabilities)
    bundles = {}
    def xnys():
        body = validate_bundle(ask('xnys_2026', 'exchange:XNYS','2026-11-26','2026-11-26'))
        bundles['xnys'] = body
        days = {d['date']:d for d in body['days']}
        require(days['2026-11-26']['state'] == 'closed', 'closed-only ask reopened')
        require(days['2026-11-27']['close'] == '2026-11-27T18:00:00Z', 'early-close regression')
        require(days['2026-01-15']['open'] == '2026-01-15T14:30:00Z', 'winter opening regression')
        require(days['2026-07-15']['open'] == '2026-07-15T13:30:00Z', 'summer opening regression')
        require(body['coverage'] == {'start':'2026-01-01','end':'2026-12-31','complete':True}, 'annual coverage differs')
        require(all(d['evidenceStatus']=='library_baseline' for d in body['days']), 'unexpected source authority')
        observations['xnys'] = {'digest':body['digest'],'coverage':body['coverage'],'source':body['source'],
                                'authority':'library_baseline; not exchange-certified or historical local knowledge'}
    check('closed_only_early_close_and_dst_survive_installed_route', xnys)
    def breaks():
        body = validate_bundle(ask('xhkg_2026','exchange:XHKG','2026-01-02','2026-01-02'))
        day = next(d for d in body['days'] if d['date']=='2026-01-02')
        require(day['segments'] == [{'start':'2026-01-02T01:30:00Z','end':'2026-01-02T04:00:00Z'},
                                    {'start':'2026-01-02T05:00:00Z','end':'2026-01-02T08:00:00Z'}], 'break segmentation changed')
    check('intraday_break_segments_preserved', breaks)
    for name, calendar, start, end, status in [
        ('unknown','constructor','2026-01-01','2026-01-02',422),
        ('reversed','exchange:XNYS','2026-02-01','2026-01-01',422),
        ('invalid_date','exchange:XNYS','2026-02-30','2026-03-01',422),
        ('oversized','exchange:XNYS','2000-01-01','2021-01-01',413),
        ('unavailable_future','exchange:XSES','2027-01-01','2027-01-02',422)]:
        check(name+'_refuses_without_fallback', lambda n=name,c=calendar,s=start,e=end,st=status: ask(n,c,s,e,st))
    def clipped():
        body = validate_bundle(ask('clipped_xshg_1990','exchange:XSHG','1990-01-01','1990-12-31'))
        require(body['coverage']['start']=='1990-12-03', 'unexpected supplier bounds')
        require(all(d['date'] >= body['coverage']['start'] for d in body['days']), 'uncovered dates fabricated')
        observations['clipped_request'] = {'http_status':200,'requested_start':'1990-01-01',
            'served_coverage':body['coverage'],'caller_must_refuse_uncovered_resolution':True}
    check('clipped_coverage_is_explicit_not_a_closure', clipped)
    def identities():
        original = bundles['xnys']
        changed = deepcopy(original)
        changed['generatedAt'] = '2001-01-01T00:00:00Z'
        validate_bundle(changed)
        require(bundle_digest(changed)==original['digest'], 'generation time changed semantic digest')
        require(sha256(encoded(changed)).digest()!=sha256(encoded(original)).digest(), 'exact bytes ignored generation time')
        changed = deepcopy(original)
        day = next(d for d in changed['days'] if d['date']=='2026-11-27')
        day['close'] = '2026-11-27T19:00:00Z'
        day['segments'][-1]['end'] = day['close']
        changed['digest'] = bundle_digest(changed)
        validate_bundle(changed)
        require(changed['digest'] != original['digest'], 'synthetic correction reused digest')
        require(next(d for d in original['days'] if d['date']=='2026-11-27')['close']=='2026-11-27T18:00:00Z', 'original mutated')
        observations['correction_test'] = 'synthetic mutation only; not a real source correction'
    check('semantic_and_exact_byte_identities_are_distinct', identities)
    def rejects_gap():
        body = deepcopy(bundles['xnys']);body['days'].pop();body['digest']=bundle_digest(body)
        try:
            validate_bundle(body)
        except ValueError:
            return
        raise ValueError('complete coverage accepted missing day')
    check('complete_coverage_cannot_hide_a_missing_day', rejects_gap)
    report = {'format':'calendar-source-qualification-v1',
        'status':'pass' if all(c['status']=='pass' for c in checks) else 'fail',
        'observed_at':datetime.now(timezone.utc).isoformat(),
        'harness':'installed FastAPI route packages in disposable offline container; not full OpenBB/gateway deployment',
        'versions':{name:version(name) for name in ['openbq-calendar','openbq-routes','exchange_calendars','pydantic','tzdata']},
        'installed_source_inventory':installed,
        'qualification_program_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'requests':requests,'checks':checks,'observations':observations,
        'limits':['not TemporalDB accepted capture/publication', 'not historical provider publication evidence',
                  'not Security Master integration qualification', 'tzdata package label alone does not identify the active timezone backend']}
    return {'report':report,'responses':{name:base64.b64encode(raw).decode() for name,raw in responses.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside(), allow_nan=False));return
    if args.verify:
        report = verify_evidence(args.verify)
        print(json.dumps({'integrity':'pass','qualification_status':report.get('status')}));return
    if not args.image or not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image) or args.output is None:
        parser.error('--image sha256:<full ID> and --output <new-directory> required')
    if args.output.exists():
        raise FileExistsError('choose a new evidence directory; previous observations are immutable')
    result = subprocess.run(['docker','run','--rm','--network','none','--entrypoint','python',
        '-v',str(Path(__file__).resolve())+':/qualification.py:ro',
        '-v',str(ROOT/'calendar-core/openbq_calendar')+':/expected/calendar:ro',
        '-v',str(ROOT/'v4/routes/openbq_routes/calendar_v1.py')+':/expected/calendar_v1.py:ro',
        args.image,'/qualification.py','--inside'], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('offline calendar harness failed: ' + result.stderr[-4096:])
    payload = json.loads(result.stdout)
    report = payload['report'] | {'image_id':args.image}
    responses = {name:base64.b64decode(raw, validate=True) for name,raw in payload['responses'].items()}
    write_evidence(args.output, report, responses)
    verify_evidence(args.output)
    print(json.dumps({'status':report['status'],'checks':len(report['checks']),'output':str(args.output)}))
    if report['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
