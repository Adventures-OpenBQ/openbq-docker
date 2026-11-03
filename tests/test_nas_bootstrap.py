# SPDX-License-Identifier: Apache-2.0
"""Bootstrap accepts only the private fresh staging namespace."""

import importlib.util
import json
from pathlib import Path
import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / "v11/nas" / name
    assert path.exists(), "staging bootstrap is not implemented"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(tmp_path):
    path = tmp_path / "candidate"
    load("provision.py").prepare_bundle(
        path,
        {
            "image_id": "sha256:" + "a" * 64,
            "source_commit": "b" * 40,
            "platform": "linux/amd64",
        },
    )
    return path


def test_bootstrap_configuration_is_narrow_and_keeps_admin_out_of_runtime(tmp_path):
    module = load("bootstrap.py")
    path = bundle(tmp_path)
    config = module.read_configuration(path)
    assert config["worker"]["TEMPORALDB_S3_ENDPOINT"] == "http://s3:9000"
    assert config["release"]["status"] == "prepared_not_started"
    assert "TEMPORALDB_MIGRATION_DSN" not in config["worker"]


@pytest.mark.parametrize(
    "old,new",
    [
        ("host=postgres", "host=production"),
        ("s3://temporaldb-v11/hot/", "s3://openbb-delta/"),
        ("http://s3:9000", "http://production:9000"),
    ],
)
def test_bootstrap_refuses_existing_or_external_store_configuration(tmp_path, old, new):
    module = load("bootstrap.py")
    path = bundle(tmp_path)
    worker = path / "worker.env"
    worker.write_text(worker.read_text().replace(old, new))
    with pytest.raises(ValueError):
        module.read_configuration(path)


def test_bootstrap_refuses_provider_acquisition_and_unexpected_project(tmp_path):
    module = load("bootstrap.py")
    path = bundle(tmp_path)
    worker = path / "worker.env"
    worker.write_text(
        worker.read_text().replace(
            "TEMPORALDB_ACQUISITION={}", 'TEMPORALDB_ACQUISITION={"eodhd":{}}'
        )
    )
    with pytest.raises(ValueError):
        module.read_configuration(path)
    worker.write_text(
        worker.read_text().replace(
            'TEMPORALDB_ACQUISITION={"eodhd":{}}', "TEMPORALDB_ACQUISITION={}"
        )
    )
    compose = path / "compose.staging.yaml"
    value = json.loads(compose.read_text())
    value["name"] = "openbq-stack"
    compose.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.read_configuration(path)


def test_candidate_image_bootstraps_and_restarts_with_its_own_stores(tmp_path):
    import os
    import socket
    import subprocess
    import time
    import urllib.request
    import urllib.error
    from uuid import uuid4

    image = os.environ.get("NAS_BOOTSTRAP_TEST_IMAGE")
    if not image:
        pytest.skip("explicit local amd64 candidate image required")
    root = tmp_path / "candidate"
    metadata = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]
    assert metadata["Architecture"] == "amd64"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    load("provision.py").prepare_bundle(
        root,
        {
            "image_id": metadata["Id"],
            "source_commit": metadata["Config"]["Labels"][
                "org.opencontainers.image.revision"
            ],
            "platform": "linux/amd64",
        },
        port=port,
    )
    # Use the local locked fixture images by immutable ID. Docker Desktop's
    # classic store cannot hold both platform variants of these index references.
    # The candidate API/worker remain amd64; native NAS acceptance is separate.
    compose_path = root / "compose.staging.yaml"
    definition = json.loads(compose_path.read_text())
    for name in ("postgres", "s3"):
        reference = definition["services"][name]["image"]
        data_image = json.loads(
            subprocess.check_output(
                ["docker", "image", "inspect", reference], text=True
            )
        )[0]
        definition["services"][name].update(
            image=data_image["Id"],
            platform="linux/" + data_image["Architecture"],
            pull_policy="never",
        )
    compose_path.write_text(json.dumps(definition))
    project = "nas-bootstrap-fixture-" + uuid4().hex[:12]
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "-f",
        str(root / "compose.staging.yaml"),
    ]
    bootstrap_path = Path(__file__).resolve().parents[1] / "v11/nas/bootstrap.py"

    def run(args, timeout=180, *, raw=False):
        result = subprocess.run(
            args if raw else compose + args,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            import re

            summary = re.findall(
                r"staging bootstrap failed during [a-z_]+: [A-Za-z]+ errno=(?:[0-9]+|None) at [A-Za-z0-9_.-]+:[0-9]+",
                result.stderr,
            )
            pytest.fail(
                summary[-1] if summary else "isolated Docker staging command failed"
            )
        return result

    try:
        run(["up", "-d", "--wait", "--wait-timeout", "120", "postgres", "s3"])
        result = run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "--name",
                project + "-bootstrap",
                "--label",
                "com.docker.compose.project=" + project,
                "--label",
                "com.docker.compose.service=bootstrap-fixture",
                "--network",
                project + "_default",
                "--read-only",
                "--memory",
                "2g",
                "--cpus",
                "1",
                "--user",
                "0:0",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_OVERRIDE",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
                "--tmpfs",
                "/run/temporaldb/runtime:rw,exec,nosuid,nodev,size=1073741824,mode=1777",
                "--mount",
                "type=bind,src=" + str(bootstrap_path) + ",dst=/bootstrap.py,readonly",
                "--mount",
                "type=bind,src=" + str(root) + ",dst=/config,readonly",
                "--mount",
                "type=volume,src=" + project + "_archive,dst=/archive",
                "--mount",
                "type=volume,src=" + project + "_evidence,dst=/evidence",
                "--env-file",
                str(root / "worker.env"),
                "--entrypoint",
                "python",
                metadata["Id"],
                "/bootstrap.py",
            ],
            timeout=300,
            raw=True,
        )
        initialized = json.loads(result.stdout.splitlines()[-1])
        assert (
            initialized["status"] == "initialized_not_started"
            and initialized["provider_acquisition_enabled"] is False
        )
        for name in ("api.env", "worker.env"):
            path = root / name
            path.write_text(
                path.read_text().replace(
                    "UNPROVISIONED", initialized["environment_digest"]
                )
            )
        run(["up", "-d", "--no-deps", "temporaldb-api", "temporaldb-worker"])

        def ready():
            for _ in range(90):
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:" + str(port) + "/ready", timeout=2
                    ) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(1)
            pytest.fail("staging candidate did not become ready")

        ready()
        api = {
            line.partition("=")[0]: line.partition("=")[2]
            for line in (root / "api.env").read_text().splitlines()
        }
        token = next(iter(json.loads(api["TEMPORALDB_SCOPE_POLICY"])))

        def query(path, body=None):
            payload = json.dumps(body).encode() if body is not None else None
            request = urllib.request.Request(
                "http://127.0.0.1:" + str(port) + path,
                data=payload,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)

        original = {
            "query_id": str(uuid4()),
            "revision": 1,
            "title": "Staging persistence check",
            "kind": "dataset",
            "parameters": [],
            "request": {"dataset_id": "eodhd.eod", "parameters": {"symbol": "TEST.US"}},
            "temporal": {"mode": "current_corrected"},
            "schema_expectation": [],
        }
        saved = query("/temporal/v1/queries", original)
        run(["restart", "temporaldb-api", "temporaldb-worker"])
        ready()
        assert (
            query("/temporal/v1/queries/" + saved["query_id"])["query_id"]
            == saved["query_id"]
        )
        assert query("/temporal/v1/acquisition/policies")["policies"] == []
    finally:
        import sys

        try:
            logs = subprocess.run(
                compose + ["logs", "--no-color", "--tail", "100"],
                text=True,
                capture_output=True,
                timeout=30,
            )
            diagnostic = root / "service-logs.private"
            diagnostic.write_text(logs.stdout + logs.stderr)
            diagnostic.chmod(0o600)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if (
            os.environ.get("NAS_BOOTSTRAP_RETAIN_FAILURE") == "1"
            and sys.exc_info()[0] is not None
        ):
            (root / "retained-fixture.json").write_text(
                json.dumps(
                    {
                        "project": project,
                        "mode": "private failed fixture; task-owned cleanup required",
                    }
                )
            )
        else:
            run(["down", "--volumes", "--remove-orphans"])
