#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Run a check against fresh recipe state, keeping Docker's normal build cache."""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

OWNER = 'com.openbq.regression.project'


def prepare_model(model, services, project):
    """Derive an isolated model without reading any service env-file values."""
    if not re.fullmatch(r'openbq-regression-[a-z0-9][a-z0-9-]+', project):
        raise ValueError('An isolated regression project identity is required')
    available = model.get('services', {})
    selected = set()

    def include(name):
        if name in selected:
            return
        if name not in available:
            raise ValueError('A selected dependency is absent from the recipe')
        selected.add(name)
        config = available[name]
        for dep in config.get('depends_on', {}):
            include(dep)
        mode = config.get('network_mode', '')
        if mode.startswith('service:'):
            include(mode.split(':', 1)[1])
        build = config.get('build') or {}
        contexts = build.get('additional_contexts', {}) if isinstance(build, dict) else {}
        for context in contexts.values():
            if isinstance(context, str) and context.startswith('service:'):
                include(context.split(':', 1)[1])

    for service in services:
        include(service)
    result = {'name': project, 'services': {}, 'volumes': {}, 'networks': {}}

    def owned(config):
        config.setdefault('labels', {})[OWNER] = project
        return config

    for name in sorted(selected):
        service = copy.deepcopy(available[name])
        if service.get('container_name') or service.get('ports') or service.get('volumes_from'):
            raise ValueError('Fixed containers, published ports and volumes_from cannot be shared')
        mode = service.get('network_mode')
        if mode and not mode.startswith('service:') and mode != 'none':
            raise ValueError('Only recipe-owned service namespaces or isolated networks are supported')
        if service.get('build'):
            service['image'] = f'{project}-{name}:candidate'
        service.pop('profiles', None)
        service['restart'] = 'no'  # A crash must stay visible to the check.
        if service.get('hostname'):
            service['hostname'] = f'{project}-{name}'
        if 'TS_HOSTNAME' in service.get('environment', {}):
            service['environment']['TS_HOSTNAME'] = f'{project}-{name}'
        for index, mount in enumerate(service.get('volumes', [])):
            if mount['type'] == 'bind' and not mount.get('read_only'):
                if not Path(mount['source']).is_dir():
                    raise ValueError('Writable file or missing bind paths require a separate QA configuration')
                key = f'state-{name}-{index}'
                mount.clear()
                mount.update(type='volume', source=key, target=available[name]['volumes'][index]['target'])
            if mount['type'] == 'volume':
                key = mount.setdefault('source', f'anonymous-{name}-{index}')
                definition = model.get('volumes', {}).get(key, {})
                if definition.get('external') or definition.get('driver_opts'):
                    raise ValueError('External or host-backed volumes cannot qualify fresh state')
                result['volumes'][key] = owned({'name': f'{project}_{key}'})
                # A new normal volume copies directory ownership from the image.
                # nocopy would instead leave unprivileged application data root-owned.
                mount.setdefault('volume', {}).pop('nocopy', None)
        for key in service.get('networks', {}):
            definition = copy.deepcopy(model.get('networks', {}).get(key, {}))
            if definition.pop('external', False):
                raise ValueError('An external network requires an explicit separate QA recipe')
            definition.pop('name', None)
            result['networks'][key] = owned(definition)
        result['services'][name] = owned(service)
    # Preserve non-secret declarations used by selected services. File-backed
    # secret/config values remain in their original files, never in this model.
    for kind in ['configs', 'secrets']:
        used = set()
        for service in result['services'].values():
            used.update(x if isinstance(x, str) else x['source'] for x in service.get(kind, []))
        if used:
            result[kind] = {key: copy.deepcopy(model[kind][key]) for key in used}
    return result


def docker_json(args, cwd):
    return json.loads(subprocess.check_output(['docker', *args], cwd=cwd, text=True))


def remaining_resources(project, cwd):
    result = {}
    for kind, args in [('containers', ['ps', '-aq']), ('volumes', ['volume', 'ls', '-q']),
                       ('networks', ['network', 'ls', '-q'])]:
        text = subprocess.check_output(['docker', *args, '--filter', f'label={OWNER}={project}'],
                                       cwd=cwd, text=True)
        result[kind] = text.split()
    return result


def source_identity(files):
    """Do not attribute an untracked archive to an enclosing notebook checkout."""
    receipts = []
    revisions = set()
    tracked = True
    dirty = False
    for file in files:
        path = Path(file).resolve()
        receipts.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        git = ['git', '-C', str(path.parent)]
        found = subprocess.run([*git, 'ls-files', '--error-unmatch', '--', path.name],
                               capture_output=True)
        if found.returncode:
            tracked = False
            continue
        revision = subprocess.run([*git, 'rev-parse', 'HEAD'], capture_output=True, text=True)
        if revision.returncode:
            tracked = False
            continue
        revisions.add(revision.stdout.strip())
        dirty |= bool(subprocess.check_output([*git, 'status', '--porcelain']))
    return {'source_revision': next(iter(revisions)) if tracked and len(revisions) == 1 else None,
            'source_dirty': dirty if tracked else None, 'recipe_files': receipts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regression', action='store_true', required=True,
                        help='fresh isolated project/state; normal Docker volume initialization')
    parser.add_argument('-f', '--file', action='append', default=[])
    parser.add_argument('--service', action='append', default=[])
    parser.add_argument('--verified-images', type=Path,
                        help='JSON mapping of prebuilt service names to exact qualified image IDs')
    parser.add_argument('--report', type=Path, required=True, help='private JSON result receipt')
    parser.add_argument('--wait-timeout', type=int, default=300)
    parser.add_argument('--plan', action='store_true', help='validate isolation without building or starting')
    parser.add_argument('check', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.report.exists():
        raise ValueError('Use a new receipt path; existing regression evidence is preserved')
    if args.wait_timeout <= 0:
        parser.error('--wait-timeout must be positive')
    check = args.check[1:] if args.check[:1] == ['--'] else args.check
    if not args.plan and not check:
        parser.error('Supply a check command after -- (or use --plan)')
    cwd = Path.cwd()
    project = 'openbq-regression-' + secrets.token_hex(8)
    files = args.file or ['docker-compose.yml']
    source_command = ['compose', '--project-directory', str(cwd)]
    for file in files:
        source_command += ['-f', str(Path(file).resolve())]
    model = docker_json([*source_command, 'config', '--format', 'json',
                         '--no-interpolate', '--no-env-resolution'], cwd)
    model = prepare_model(model, args.service or ['openbq-api'], project)
    report = {'project': project, 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'services': sorted(model['services']), 'fresh_project_and_state': True,
              'volume_initialization': 'normal Docker image directory ownership; no nocopy override',
              'build_policy': 'Compose builds selected dependency closure using normal layer cache',
              'status': 'planned' if args.plan else 'running', 'images': {}}
    report.update(source_identity(files))
    bindings = json.loads(args.verified_images.read_text()) if args.verified_images else {}
    for name, service in model['services'].items():
        if not service.get('build') and not args.plan:
            image = service.get('image', '')
            actual = docker_json(['image', 'inspect', image], cwd)[0]['Id']
            if bindings.get(name) != actual:
                raise ValueError('A prebuilt service requires an exact qualified image-ID binding')
            report['images'][name] = actual
    if args.plan:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print('Regression isolation plan validated; no resources created.')
        return 0
    if any(remaining_resources(project, cwd).values()):
        raise ValueError('Regression identity already has resources; refusing to reuse them')
    code = 1
    with tempfile.TemporaryDirectory(prefix='openbq-regression-') as tmp:
        config = Path(tmp) / 'compose.json'
        config.write_text(json.dumps(model))
        config.chmod(0o600)
        compose = ['docker', 'compose', '--project-directory', str(cwd), '-p', project, '-f', str(config)]
        try:
            build = [name for name, service in model['services'].items() if service.get('build')]
            if build:
                subprocess.run([*compose, 'build', *build], cwd=cwd, check=True)
            subprocess.run([*compose, 'up', '-d', '--no-build', '--pull', 'never',
                            '--force-recreate', '--renew-anon-volumes', '--wait',
                            '--wait-timeout', str(args.wait_timeout)], cwd=cwd, check=True)
            containers = {}
            for name in model['services']:
                cid = subprocess.check_output([*compose, 'ps', '-q', name], cwd=cwd, text=True).strip()
                if not cid:
                    raise ValueError('A selected service did not remain running')
                # Do not copy Config.Env into receipts or console output.
                image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', cid],
                                                cwd=cwd, text=True).strip()
                containers[name] = cid
                report['images'][name] = image
            environment = {**os.environ, 'OPENBQ_REGRESSION_PROJECT': project,
                           'OPENBQ_REGRESSION_CONTAINERS': json.dumps(containers)}
            code = subprocess.run(check, cwd=cwd, env=environment).returncode
            report['check_exit_code'] = code
        except subprocess.CalledProcessError as error:
            code = error.returncode or 1
            report['failure_stage'] = 'build-or-start'
        except (OSError, ValueError):
            code = 1
            report['failure_stage'] = 'runtime-or-check-setup'
        finally:
            down = subprocess.run([*compose, 'down', '--volumes', '--remove-orphans'], cwd=cwd)
            left = remaining_resources(project, cwd)
            report['cleanup'] = {'compose_down_exit': down.returncode,
                                 'owned_resources_remaining': left,
                                 'pass': down.returncode == 0 and not any(left.values())}
            if not report['cleanup']['pass']:
                code = code or 1
            report['status'] = 'pass' if code == 0 else 'fail'
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('Regression ' + report['status'] + '; owned cleanup ' + ('passed' if report['cleanup']['pass'] else 'failed'))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        # Provider/config values can occur inside command exceptions. Keep the
        # diagnostic categorical rather than echoing their raw payload.
        print('Regression preflight failed; check recipe, image bindings and Docker access.', file=sys.stderr)
        sys.exit(2)
