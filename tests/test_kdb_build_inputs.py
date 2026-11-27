"""Missing KX release selection must fail before download or resource creation."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_builder_rejects_an_empty_release_before_package_or_network_commands():
    text = (ROOT / "kdb-x/Dockerfile").read_text()
    early_guard = text.split("RUN set -eux;", 1)[1].split("apt-get", 1)[0]
    early_guard = early_guard.replace("\\\n", "\n")
    for version, should_pass in [("", False), ("fixture-release", True)]:
        result = subprocess.run(["sh", "-ec", early_guard],
                                env={"PATH": os.defpath, "KX_VERSION": version},
                                capture_output=True, text=True)
        assert (result.returncode == 0) is should_pass


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker Compose CLI required")
def test_local_builder_requires_an_explicit_release_in_the_resolved_recipe():
    command = ["docker", "compose", "--profile", "live", "-f", "docker-compose.yml",
               "-f", "compose.kdb-build.yml", "config", "--no-env-resolution", "--format", "json"]
    environment = {key: value for key, value in os.environ.items() if key != "KX_VERSION"}
    missing = subprocess.run(command, cwd=ROOT, env=environment,
                             capture_output=True, text=True, timeout=15)
    assert missing.returncode != 0
    assert "KX_VERSION" in missing.stderr
    explicit = subprocess.run(command, cwd=ROOT, env=environment | {"KX_VERSION": "fixture-release"},
                              capture_output=True, text=True, timeout=15, check=True)
    service = json.loads(explicit.stdout)["services"]["openbq-kdb"]
    assert service["build"]["args"]["KX_VERSION"] == "fixture-release"


@pytest.mark.skipif(not shutil.which('docker'), reason='Docker Compose CLI required')
@pytest.mark.parametrize('secured', [False, True])
def test_reader_recipes_default_to_the_locally_built_kdb_image(secured):
    command = ['docker', 'compose', '--profile', 'live', '-f', 'docker-compose.yml']
    if secured:
        command += ['-f', 'compose.chart-stream.yml']
    command += ['config', '--no-env-resolution', '--format', 'json']
    environment = {key: value for key, value in os.environ.items() if key != 'KDB_IMAGE'}
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                            text=True, timeout=15, check=True)
    service = json.loads(result.stdout)['services']['openbq-kdb']
    image = service['build']['args']['KDB_BASE_IMAGE'] if secured else service['image']
    assert image == 'openbq-kdb-x:local'
