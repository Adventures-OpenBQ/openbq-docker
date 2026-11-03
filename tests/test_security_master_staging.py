# SPDX-License-Identifier: Apache-2.0
"""Only a private standalone Security Master store may be selected."""

import importlib.util
import json
from pathlib import Path
import stat
import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "v11/security-master/provision.py"
    assert path.exists(), "Security Master staging preparation is not implemented"
    spec = importlib.util.spec_from_file_location("sm_provision", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def receipt(**changes):
    return {
        "image_id": "sha256:" + "a" * 64,
        "source_commit": "b" * 40,
        "platform": "linux/amd64",
        **changes,
    }


def test_fresh_private_service_is_isolated_authenticated_and_provider_silent(tmp_path):
    out = tmp_path / "new"
    module().prepare_bundle(out, receipt())
    compose = json.loads((out / "compose.staging.yaml").read_text())
    assert compose["name"] == "openbq-v11-security-master"
    assert compose["networks"]["default"]["internal"] is True
    assert compose["volumes"] == {"data": {}}
    assert set(compose["services"]) == {"security-master"}
    service = compose["services"]["security-master"]
    assert (
        service["image"] == receipt()["image_id"] and service["pull_policy"] == "never"
    )
    assert service["volumes"] == ["data:/data"] and service["ports"] == [
        "127.0.0.1:18089:6905"
    ]
    assert service["read_only"] and service["user"] == "65532:65532"
    assert service["mem_limit"] > 0 and service["cpus"] > 0
    env = dict(
        line.split("=", 1) for line in (out / "service.env").read_text().splitlines()
    )
    assert env["SECURITY_MASTER_ROOT"] == "/data/security_master"
    assert (
        env["SECURITY_MASTER_ACQUISITION"] == "disabled"
        and env["OPENBB_API_AUTH"] == "true"
    )
    assert (
        len(env["OPENBB_API_PASSWORD"]) == 64
        and len(env["SECURITY_MASTER_PREFLIGHT_SECRET"]) == 64
    )
    assert env["OPENBB_API_PASSWORD"] != env["SECURITY_MASTER_PREFLIGHT_SECRET"]
    assert set(env) == {
        "SECURITY_MASTER_ROOT",
        "SECURITY_MASTER_ACQUISITION",
        "SECURITY_MASTER_SQL",
        "SECURITY_MASTER_PREFLIGHT_SECRET",
        "SECURITY_MASTER_MEMORY_LIMIT",
        "SECURITY_MASTER_THREADS",
        "OPENBB_API_AUTH",
        "OPENBB_API_USERNAME",
        "OPENBB_API_PASSWORD",
    }
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    out2 = tmp_path / "another"
    module().prepare_bundle(out2, receipt())
    assert (out2 / "service.env").read_bytes() != (out / "service.env").read_bytes()


@pytest.mark.parametrize(
    "changes",
    [{"image_id": "latest"}, {"platform": "linux/arm64"}, {"source_commit": "dirty"}],
)
def test_mutable_or_wrong_artifact_is_rejected(tmp_path, changes):
    out = tmp_path / "new"
    with pytest.raises(ValueError):
        module().prepare_bundle(out, receipt(**changes))
    assert not out.exists()


def test_existing_service_configuration_is_never_overwritten(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "service.env").write_text("preserve")
    with pytest.raises(FileExistsError):
        module().prepare_bundle(out, receipt())
    assert (out / "service.env").read_text() == "preserve"
