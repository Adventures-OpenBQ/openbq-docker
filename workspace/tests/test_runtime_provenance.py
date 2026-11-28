"""The real runtime verifier accepts exactly the current packaged build inputs."""
from pathlib import Path
import hashlib
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / 'workspace'


def record():
    source = json.loads((WORKSPACE / 'source.json').read_text())
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    return {'status': 'complete', 'upstream': source['commit'],
            'patches': {p.name: sha(p) for p in sorted((WORKSPACE / 'patches').glob('*.patch'))},
            'packaged': {name: sha(WORKSPACE / name) for name in
                         ('postgres/migrate_workspace.py', 'postgres/schema_manifest.json',
                          'scripts/strip_public_test_key.py')},
            'resolved_lock': sha(WORKSPACE / 'resolved-poetry.lock'),
            'source_record': source['postgresql_build']['assembly']['source_record']}


def verify(value):
    script = (WORKSPACE / 'scripts/verify-postgres.sh').read_text()
    code = script.split("python3 - <<'PROVENANCE'\n", 1)[1].split('\nPROVENANCE', 1)[0]
    with patch.dict(os.environ, DOCKER='offline-fixture', WORKSPACE_TEST_IMAGE='sha256:' + 'a' * 64), \
         patch('subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(value))) as run:
        exec(compile(code, 'workspace-runtime-provenance', 'exec'), {})
    assert run.call_count == 1


def test_complete_current_packaged_inputs_are_accepted(monkeypatch):
    monkeypatch.chdir(ROOT)
    verify(record())


@pytest.mark.parametrize('tamper', ['missing-helper', 'changed-patch'])
def test_missing_or_changed_current_inputs_are_rejected(monkeypatch, tamper):
    monkeypatch.chdir(ROOT)
    value = record()
    if tamper == 'missing-helper':
        del value['packaged']['scripts/strip_public_test_key.py']
    else:
        value['patches']['007-workspace-request-boundaries.patch'] = '0' * 64
    with pytest.raises(AssertionError):
        verify(value)
