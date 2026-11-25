#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Run checks against fresh recipe state, retaining Docker's ordinary layer cache."""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile

OWNER = 'com.openbq.regression.project'
_active_child = None


class RegressionInterrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def _interrupt(signum, _frame):
    raise RegressionInterrupted(signum)


def _stop_child(process):
    if process.poll() is not None:
        return
    if os.name == 'posix':
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def run_command(args, cwd=None, env=None, check=False, stream=False, timeout=None):
    """Docker diagnostics stay in memory; only the supplied check may stream."""
    global _active_child
    process = subprocess.Popen(args, cwd=cwd, env=env, text=True,
                               stdout=None if stream else subprocess.PIPE,
                               stderr=None if stream else subprocess.PIPE,
                               start_new_session=os.name == 'posix')
    _active_child = process
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        _stop_child(process)
        raise
    finally:
        _active_child = None
    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check and result.returncode:
        raise subprocess.CalledProcessError(result.returncode, args, stdout, stderr)
    return result


def _mapping(value, labels=False):
    if value is None:
        return {}
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return {x.partition('=')[0]: x.partition('=')[2] if '=' in x else '' if labels else None for x in value}
    raise ValueError('Unsupported mapping representation')


def _dependencies(config):
    value = config.get('depends_on', {})
    return {x: {'condition': 'service_started'} for x in value} if isinstance(value, list) else value


def _namespace_dependencies(config):
    return [value.split(':', 1)[1] for key in ['network_mode', 'pid', 'ipc']
            if isinstance(value := config.get(key), str) and value.startswith('service:')]


def runtime_services(model, services):
    available = model.get('services', {}); runtime = set(); completed = set()
    def include(name):
        if name in runtime:
            return
        if name not in available:
            raise ValueError('A selected dependency is absent from the recipe')
        runtime.add(name)
        for dep, options in _dependencies(available[name]).items():
            if options.get('condition') == 'service_completed_successfully':
                completed.add(dep)
            include(dep)
        for dep in _namespace_dependencies(available[name]):
            include(dep)
    for service in services:
        include(service)
    return runtime, completed


def _build_contexts(config):
    build = config.get('build') or {}
    return _mapping(build.get('additional_contexts', {})) if isinstance(build, dict) else {}


def _literal_path(value):
    if not isinstance(value, str) or re.search(r'\$(?:\{|[A-Za-z_])', value):
        raise ValueError('Unresolved structural path in the canonical recipe')
    return value


def prepare_model(model, services, project):
    """Prepare a fully resolved structural model; never read service env files."""
    if not re.fullmatch(r'openbq-regression-[a-z0-9][a-z0-9-]+', project):
        raise ValueError('An isolated regression project identity is required')
    selected, _ = runtime_services(model, services)
    available = model['services']
    pending = list(selected)
    while pending:
        name = pending.pop()
        for context in _build_contexts(available[name]).values():
            if isinstance(context, str) and context.startswith('service:'):
                more, _ = runtime_services(model, [context.split(':', 1)[1]])
                pending.extend(more - selected); selected.update(more)
    result = {'name': project, 'services': {}, 'volumes': {}, 'networks': {}}
    allocated = set(model.get('volumes', {}))
    bind_state = {}
    def new_key(stem):
        key = stem; index = 0
        while key in allocated:
            index += 1; key = stem + '-' + str(index)
        allocated.add(key)
        return key
    def owned(config):
        config['labels'] = _mapping(config.get('labels'), labels=True)
        config['labels'][OWNER] = project
        return config
    for name in sorted(selected):
        service = copy.deepcopy(available[name])
        if service.get('container_name') or service.get('ports') or service.get('volumes_from'):
            raise ValueError('Fixed containers, published ports and volumes_from are refused')
        allowed = {'network_mode': {'none'}, 'pid': set(), 'ipc': {'private', 'shareable'},
                   'uts': {'private'}, 'userns_mode': {'private'}, 'cgroup': {'private'}}
        for key, modes in allowed.items():
            value = service.get(key)
            if value is None:
                continue
            if key in ['network_mode', 'pid', 'ipc'] and isinstance(value, str) and value.startswith('service:'):
                continue
            if not isinstance(value, str) or value not in modes:
                raise ValueError('Foreign or unresolved namespace configuration is refused')
        if service.get('scale', 1) != 1 or service.get('deploy', {}).get('replicas', 1) != 1:
            raise ValueError('Only single-replica QA services are supported')
        build = service.get('build')
        if build:
            if isinstance(build, str):
                build = service['build'] = {'context': build}
            if build.get('outputs') or build.get('cache_to'):
                raise ValueError('Additional build outputs are not regression-owned')
            build.pop('tags', None)
            if 'context' in build:
                _literal_path(build['context'])
            service['image'] = f'{project}-{name}:candidate'
        elif 'image' in service:
            _literal_path(service['image'])
        service.pop('profiles', None)
        service['restart'] = 'no'
        if service.get('hostname'):
            service['hostname'] = f'{project}-{name}'
        service['environment'] = _mapping(service.get('environment'))
        if 'TS_HOSTNAME' in service['environment']:
            service['environment']['TS_HOSTNAME'] = f'{project}-{name}'
        for index, mount in enumerate(service.get('volumes', [])):
            if 'read_only' in mount and type(mount['read_only']) is not bool:
                raise ValueError('Mount permissions must be resolved booleans')
            _literal_path(mount['target'])
            if mount['type'] == 'bind':
                _literal_path(mount['source'])
                if not mount.get('read_only', False):
                    if not Path(mount['source']).is_dir():
                        raise ValueError('Writable file or missing bind paths need isolated QA configuration')
                    source = str(Path(mount['source']).resolve())
                    if source not in bind_state:
                        bind_state[source] = new_key(f'state-{name}-{index}')
                    target = mount['target']; key = bind_state[source]
                    mount.clear(); mount.update(type='volume', source=key, target=target)
            if mount['type'] == 'volume':
                key = mount.get('source') or new_key(f'anonymous-{name}-{index}')
                mount['source'] = key
                definition = model.get('volumes', {}).get(key, {})
                if definition.get('external') or definition.get('driver_opts') or definition.get('driver', 'local') != 'local':
                    raise ValueError('External or host-backed volumes cannot qualify fresh state')
                result['volumes'][key] = owned({'name': f'{project}_{key}'})
                mount.setdefault('volume', {}).pop('nocopy', None)
        for key in service.get('networks', {}):
            definition = copy.deepcopy(model.get('networks', {}).get(key, {}))
            if definition.pop('external', False) or definition.get('driver', 'bridge') != 'bridge':
                raise ValueError('Only new private bridge networks are supported')
            definition.pop('name', None)
            result['networks'][key] = owned(definition)
        result['services'][name] = owned(service)
    for kind in ['configs', 'secrets']:
        used = set()
        for service in result['services'].values():
            references = list(service.get(kind, []))
            if kind == 'secrets' and isinstance(service.get('build'), dict):
                references += service['build'].get('secrets', [])
            used.update(x if isinstance(x, str) else x['source'] for x in references)
        if used:
            result[kind] = {key: copy.deepcopy(model[kind][key]) for key in used}
    return result


def load_recipe(files):
    files = [Path(file).resolve() for file in files]
    base = files[0].parent
    command = ['docker', 'compose', '--project-directory', str(base)]
    for file in files:
        command += ['-f', str(file)]
    # Typed fields and paths are resolved exactly once, in memory. Env-file
    # contents stay in the original private files; no raw diagnostics escape.
    result = run_command([*command, 'config', '--format', 'json', '--no-env-resolution'], cwd=base, check=True)
    # Compose serializes literal dollars as $$ so its own output can be read
    # again. Our environment indirection prevents that second interpretation;
    # decode this serialization layer once before binding semantic values.
    def decoded(value):
        if isinstance(value, str):
            return value.replace('$$', '$')
        if isinstance(value, list):
            return [decoded(x) for x in value]
        if isinstance(value, dict):
            return {key: decoded(child) for key, child in value.items()}
        return value
    return decoded(json.loads(result.stdout)), base


def cloaked_model(model):
    """Persist references only, with all resolved string values in process memory."""
    prefix = 'OPENBQ_REGRESSION_VALUE_' + secrets.token_hex(8).upper() + '_'
    environment = {}
    def cloak(value):
        if isinstance(value, str):
            key = prefix + str(len(environment)); environment[key] = value
            return '${' + key + '}'
        if isinstance(value, list):
            return [cloak(x) for x in value]
        if isinstance(value, dict):
            return {key: cloak(child) for key, child in value.items()}
        return value
    return cloak(model), environment


def pin_images(model, names, bindings, inspect_image, include_built=False):
    expected = {}
    for name in names:
        service = model['services'][name]
        if service.get('build') and not include_built:
            continue
        actual = inspect_image(service['image'])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', actual):
            raise ValueError('Invalid image identity')
        if not service.get('build') and bindings.get(name) != actual:
            raise ValueError('A prebuilt service needs an exact qualified image-ID binding')
        service['image'] = actual
        expected[name] = actual
    return expected


def remaining_resources(project, cwd, env=None):
    result = {}
    for kind, args in [('containers', ['ps', '-aq']), ('volumes', ['volume', 'ls', '-q']),
                       ('networks', ['network', 'ls', '-q'])]:
        values = set()
        for label in [OWNER, 'com.docker.compose.project']:
            response = run_command(['docker', *args, '--filter', f'label={label}={project}'],
                                   cwd=cwd, env=env, check=True, timeout=15)
            values.update(response.stdout.split())
        result[kind] = sorted(values)
    return result


def cleanup_project(compose, project, cwd, env):
    result = {'pass': False, 'verification': 'unknown', 'owned_resources_remaining': None}
    try:
        response = run_command([*compose, 'down', '--volumes', '--remove-orphans', '--timeout', '10'],
                               cwd=cwd, env=env, timeout=30)
        result['compose_down_exit'] = response.returncode
    except (OSError, subprocess.SubprocessError):
        result['compose_down_exit'] = None
    try:
        left = remaining_resources(project, cwd, env)
        result.update(owned_resources_remaining=left, verification='complete',
                      **{'pass': result['compose_down_exit'] == 0 and not any(left.values())})
    except (OSError, subprocess.SubprocessError):
        result['inventory_error'] = 'Docker resource inventory unavailable'
    return result


def publish_report(report, path):
    """Publish a complete private receipt atomically, never replacing another proof."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=path.name + '.unpublished-', dir=path.parent)
    pending = Path(pending)
    with os.fdopen(fd, 'w') as file:
        json.dump(report, file, indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
    try:
        os.link(pending, path)  # Atomic no-clobber; pending is already mode0600.
    except FileExistsError:
        # Retain this run's complete private receipt beside the requested path.
        raise ValueError('Receipt conflict; an unpublished private receipt is retained') from None
    else:
        pending.unlink()


def source_identity(files):
    receipts = []; revisions = set(); tracked = True; dirty = False
    for file in files:
        path = Path(file).resolve()
        receipts.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        git = ['git', '-C', str(path.parent)]
        found = run_command([*git, 'ls-files', '--error-unmatch', '--', path.name])
        revision = run_command([*git, 'rev-parse', 'HEAD']) if found.returncode == 0 else None
        if revision is None or revision.returncode:
            tracked = False; continue
        revisions.add(revision.stdout.strip())
        dirty |= bool(run_command([*git, 'status', '--porcelain'], check=True).stdout)
    return {'source_revision': next(iter(revisions)) if tracked and len(revisions) == 1 else None,
            'source_dirty': dirty if tracked else None, 'recipe_files': receipts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regression', action='store_true', required=True)
    parser.add_argument('-f', '--file', action='append', default=[])
    parser.add_argument('--service', action='append', default=[])
    parser.add_argument('--verified-images', type=Path, help='Private JSON service-to-qualified-image-ID mapping')
    parser.add_argument('--report', type=Path, required=True, help='New private JSON receipt')
    parser.add_argument('--wait-timeout', type=int, default=300)
    parser.add_argument('--plan', action='store_true', help='Validate isolation without creating resources')
    parser.add_argument('check', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.report.exists():
        raise ValueError('Use a new receipt path; existing evidence is preserved')
    if args.wait_timeout <= 0:
        parser.error('--wait-timeout must be positive')
    check = args.check[1:] if args.check[:1] == ['--'] else args.check
    if not args.plan and not check:
        parser.error('Supply a check command after -- or use --plan')
    files = [str(Path(file).resolve()) for file in args.file or ['docker-compose.yml']]
    requested = args.service or ['openbq-api']
    project = 'openbq-regression-' + secrets.token_hex(8)
    original, base = load_recipe(files)
    runtime, completed = runtime_services(original, requested)
    model = prepare_model(original, requested, project)
    report = {'project': project, 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'services': sorted(runtime), 'build_only_services': sorted(set(model['services']) - runtime),
              'fresh_project_and_state': True, 'volume_initialization': 'normal Docker ownership; no nocopy override',
              'build_policy': 'input-aware Compose layer cache', 'status': 'planned' if args.plan else 'running',
              'images': {}, **source_identity(files)}
    if args.plan:
        publish_report(report, args.report)
        print('Regression isolation plan validated; no resources created.')
        return 0
    bindings = json.loads(args.verified_images.read_text()) if args.verified_images else {}
    def inspect_image(image):
        response = run_command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], cwd=base, check=True)
        return response.stdout.strip()
    expected = pin_images(model, runtime, bindings, inspect_image)
    if any(remaining_resources(project, base).values()):
        raise ValueError('Refusing to reuse an existing regression project')
    signals = {key: signal.getsignal(key) for key in [signal.SIGTERM, signal.SIGINT]}
    for key in signals:
        signal.signal(key, _interrupt)
    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix='openbq-regression-') as tmp:
            config = Path(tmp) / 'compose.json'
            def write_model():
                masked, values = cloaked_model(model)
                fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as file:
                    json.dump(masked, file)
                return {**os.environ, **values}
            environment = write_model()
            compose = ['docker', 'compose', '--project-directory', str(base), '-p', project, '-f', str(config)]
            try:
                build = [name for name, service in model['services'].items() if service.get('build')]
                if build:
                    response = run_command([*compose, 'build', *build], cwd=base, env=environment, check=True)
                    report['cached_build_steps'] = (response.stdout + response.stderr).count('CACHED')
                expected.update(pin_images(model, runtime, bindings, inspect_image, include_built=True))
                environment = write_model()  # Startup uses immutable IDs, including built services.
                run_command([*compose, 'up', '-d', '--no-build', '--pull', 'never', '--force-recreate',
                             '--renew-anon-volumes', '--wait', '--wait-timeout', str(args.wait_timeout), *requested],
                            cwd=base, env=environment, check=True)
                containers = {}; finished = {}
                for name in sorted(runtime):
                    response = run_command([*compose, 'ps', '--all', '-q', name], cwd=base, env=environment, check=True)
                    ids = response.stdout.split()
                    if len(ids) != 1:
                        raise ValueError('Expected exactly one owned runtime service container')
                    cid = ids[0]
                    response = run_command(['docker', 'inspect', '--format',
                                            '{{json .State}}\n{{.Image}}', cid], cwd=base, check=True)
                    lines = response.stdout.splitlines(); state = json.loads(lines[0]); image = lines[1]
                    if image != expected[name]:
                        raise ValueError('Running image differs from qualified immutable identity')
                    report['images'][name] = image
                    if state['Running']:
                        containers[name] = cid
                    elif name in completed and state['Status'] == 'exited' and state['ExitCode'] == 0:
                        finished[name] = cid
                    else:
                        raise ValueError('A selected service did not remain ready')
                report['successfully_completed_services'] = sorted(finished)
                check_env = {**os.environ, 'OPENBQ_REGRESSION_PROJECT': project,
                             'OPENBQ_REGRESSION_CONTAINERS': json.dumps(containers),
                             'OPENBQ_REGRESSION_COMPLETED_CONTAINERS': json.dumps(finished)}
                code = run_command(check, cwd=Path.cwd(), env=check_env, stream=True).returncode
                report['check_exit_code'] = code
            except RegressionInterrupted as error:
                code = 128 + error.signum; report['failure_stage'] = 'interrupted'
            except subprocess.CalledProcessError as error:
                code = error.returncode or 1; report['failure_stage'] = 'build-or-start'
            except Exception:
                code = 1; report['failure_stage'] = 'runtime-or-check-setup'
            finally:
                for key in signals:
                    signal.signal(key, signal.SIG_IGN)
                report['cleanup'] = cleanup_project(compose, project, base, environment)
                if not report['cleanup']['pass']:
                    code = code or 1
                report['status'] = 'pass' if code == 0 else 'fail'
                publish_report(report, args.report)
    finally:
        for key, handler in signals.items():
            signal.signal(key, handler)
    print('Regression ' + report['status'] + '; owned cleanup ' + ('passed' if report['cleanup']['pass'] else 'unverified'))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('Regression failed before a verified result; check recipe, bindings, receipt path and Docker access.', file=sys.stderr)
        sys.exit(2)
