# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import shutil
import subprocess
import pytest


def test_charts_overlay_configures_same_owner_without_publishing_it():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose required")
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            docker,
            "compose",
            "--profile",
            "live",
            "--profile",
            "charts-v12",
            "-f",
            "docker-compose.yml",
            "-f",
            "v12/compose.charts.yaml",
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert (
        services["live-grid"]["environment"]["LIVE_GRID_STUDY_ORIGIN"]
        == "http://arts-charts:8000"
    )
    assert not services["arts-charts"].get("ports")
    assert services["arts-charts"]["networks"] == {"openbq-internal": None}
