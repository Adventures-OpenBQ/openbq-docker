# SPDX-License-Identifier: Apache-2.0
"""NAS inventory emits deployment facts without private runtime configuration."""

import importlib.util
import json
from pathlib import Path

import pytest


def implementation():
    path = Path(__file__).resolve().parents[1] / "v11/nas/inventory.py"
    assert path.exists(), "read-only NAS inventory is not implemented"
    spec = importlib.util.spec_from_file_location("nas_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_filters_private_environment_and_unrelated_labels():
    item = implementation().container_record(
        {
            "Name": "/candidate-api",
            "Id": "c" * 64,
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Image": "candidate:staging",
                "Env": ["PRIVATE=must-not-export"],
                "Labels": {
                    "com.docker.compose.project": "staging",
                    "private": "must-not-export",
                },
            },
            "HostConfig": {
                "Memory": 1073741824,
                "NanoCpus": 1000000000,
                "Binds": ["private-config"],
            },
            "State": {
                "Status": "running",
                "Health": {"Status": "healthy", "Log": ["private-log"]},
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "staging-db",
                    "Source": "/volumes/staging-db",
                    "Destination": "/data",
                    "RW": True,
                }
            ],
            "NetworkSettings": {
                "Networks": {"staging": {"IPAddress": "private-address"}}
            },
        }
    )
    assert item["image_id"] == "sha256:" + "a" * 64
    assert item["memory_limit_bytes"] == 1073741824
    assert item["networks"] == ["staging"]
    assert item["mounts"][0]["source"] == "/volumes/staging-db"
    encoded = json.dumps(item)
    assert "must-not-export" not in encoded and "private-log" not in encoded
    assert "private-config" not in encoded and "private-address" not in encoded


def test_receipts_cannot_overwrite_prior_observations(tmp_path):
    module = implementation()
    path = tmp_path / "inventory.json"
    module.write_receipt(
        path, {"schema_version": 1, "observed_at": "2026-11-03T19:00:00Z"}
    )
    with pytest.raises(FileExistsError):
        module.write_receipt(path, {"schema_version": 1})
    assert json.loads(path.read_text())["observed_at"] == "2026-11-03T19:00:00Z"


def test_ssh_target_is_an_explicit_host_alias_without_options():
    module = implementation()
    assert module.validate_target("nas") == "nas"
    for target in ["-oProxyCommand=bad", "nas;bad", "nas bad", "user@nas", ""]:
        with pytest.raises(ValueError):
            module.validate_target(target)


def test_docker_container_without_healthcheck_can_be_inspected():
    import os
    import subprocess

    context = os.environ.get("NAS_INVENTORY_TEST_CONTEXT")
    name = os.environ.get("NAS_INVENTORY_TEST_CONTAINER")
    if not context or not name:
        pytest.skip("explicit read-only Docker integration target required")
    module = implementation()
    module.validate_target(context)
    result = subprocess.run(
        ["docker", "--context", context, "inspect", "--format", module.INSPECT, name],
        capture_output=True,
        text=True,
        check=True,
    )
    record = module.container_record(json.loads(result.stdout))
    assert record["name"] == name and record["health"] is None
