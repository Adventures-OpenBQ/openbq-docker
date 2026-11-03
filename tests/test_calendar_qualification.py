# SPDX-License-Identifier: Apache-2.0
"""Offline evidence integrity; no installed service or account data involved."""
import importlib.util
from pathlib import Path
import json
import pytest


def implementation():
    path = Path(__file__).resolve().parents[1]/'v11/calendar_source_qualification.py'
    spec = importlib.util.spec_from_file_location('calendar_qualification', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_roundtrip_preserves_response_bytes_and_refuses_overwrite(tmp_path):
    module = implementation()
    root = tmp_path/'evidence'
    raw = b'{ "days": [] }\n'
    manifest = module.write_evidence(root, {'status':'pass'}, {'closed':raw})
    assert (root/'responses/closed.json').read_bytes() == raw
    assert manifest['responses'][0]['bytes'] == len(raw)
    assert module.verify_evidence(root) == {'status':'pass'}
    with pytest.raises(FileExistsError):
        module.write_evidence(root, {}, {})


@pytest.mark.parametrize('target', ['report.json','responses/closed.json'])
def test_evidence_tampering_is_detected(tmp_path, target):
    module = implementation()
    root = tmp_path/'evidence'
    module.write_evidence(root, {'status':'pass'}, {'closed':b'{}'})
    (root/target).write_bytes(b'changed')
    with pytest.raises(ValueError):
        module.verify_evidence(root)


def test_untrusted_evidence_paths_are_rejected(tmp_path):
    module = implementation()
    with pytest.raises(ValueError):
        module.write_evidence(tmp_path/'bad', {}, {'../escape':b'{}'})
    root = tmp_path/'evidence'
    module.write_evidence(root, {}, {'closed':b'{}'})
    manifest = json.loads((root/'manifest.json').read_text())
    manifest['responses'][0]['path'] = '../escape'
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.verify_evidence(root)


def test_manifest_symlink_is_not_accepted_as_a_retained_artifact(tmp_path):
    module = implementation()
    root = tmp_path/'evidence'
    module.write_evidence(root, {}, {'closed':b'{}'})
    manifest = root/'manifest.json'
    external = tmp_path/'external.json'
    external.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(external)
    with pytest.raises(ValueError):
        module.verify_evidence(root)
