# SPDX-License-Identifier: Apache-2.0
"""Fresh staging bundles cannot accidentally select existing production stores."""

import importlib.util
import json
from pathlib import Path
import stat

import pytest


def implementation():
    path = Path(__file__).resolve().parents[1] / "v11/nas/provision.py"
    assert path.exists(), "staging bundle preparation is not implemented"
    spec = importlib.util.spec_from_file_location("nas_provision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt(**changes):
    return {
        "image_id": "sha256:" + "a" * 64,
        "source_commit": "b" * 40,
        "platform": "linux/amd64",
        **changes,
    }


def test_fresh_staging_uses_only_own_stores_loopback_and_separate_credentials(tmp_path):
    root = tmp_path / "candidate"
    implementation().prepare_bundle(root, receipt())
    compose = json.loads((root / "compose.staging.yaml").read_text())
    assert compose["name"] == "openbq-v11-staging"
    assert set(compose["services"]) == {
        "postgres",
        "s3",
        "temporaldb-api",
        "temporaldb-worker",
    }
    for name, service in compose["services"].items():
        assert service["mem_limit"] > 0 and service["cpus"] > 0
        assert not service.get("container_name")
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
        assert all(
            "external" not in volume for volume in compose.get("volumes", {}).values()
        )
        for mount in service.get("volumes", []):
            assert not mount.startswith("/") and "/share/" not in mount
    api = (root / "api.env").read_text()
    worker = (root / "worker.env").read_text()
    assert "TEMPORALDB_WORKER_DSN=" not in api and "TEMPORALDB_API_DSN=" not in worker
    assert "acquisition.run" not in api
    assert "TEMPORALDB_ACQUISITION={}" in worker
    assert "user=temporaldb_api_login " in api
    assert "user=temporaldb_worker_login " in worker
    assert api != worker and (root / "admin.env").read_text() not in api
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for path in root.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "change",
    [{"platform": "linux/arm64"}, {"image_id": "latest"}, {"source_commit": "dirty"}],
)
def test_wrong_architecture_or_mutable_artifact_is_rejected_before_writing(
    tmp_path, change
):
    path = tmp_path / "candidate"
    with pytest.raises(ValueError):
        implementation().prepare_bundle(path, receipt(**change))
    assert not path.exists()


def test_bundle_preparation_does_not_replace_existing_configuration(tmp_path):
    path = tmp_path / "candidate"
    path.mkdir()
    (path / "api.env").write_text("previous")
    with pytest.raises(FileExistsError):
        implementation().prepare_bundle(path, receipt())
    assert (path / "api.env").read_text() == "previous"


def test_docker_compose_resolves_only_fresh_scoped_staging_resources(tmp_path):
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("Docker Compose required for configuration qualification")
    root = tmp_path / "candidate"
    implementation().prepare_bundle(root, receipt())
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(root / "compose.staging.yaml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    compose = json.loads(result.stdout)
    assert compose["networks"]["default"]["internal"] is True
    assert compose["services"]["temporaldb-api"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert all(
        value["name"].startswith("openbq-v11-staging_")
        for value in compose["volumes"].values()
    )
    for name in ["temporaldb-api", "temporaldb-worker"]:
        assert compose["services"][name]["pull_policy"] == "never"
        assert (
            compose["services"][name]["environment"]["TEMPORALDB_ENVIRONMENT_DIGEST"]
            == "UNPROVISIONED"
        )
