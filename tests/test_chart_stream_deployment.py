# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Compile the opt-in deployment with Compose, without loading operator secrets."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_chart_overlay_connects_named_clients_without_publishing_q():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose is required for deployment compilation")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [docker, "compose", "--profile", "live", "--profile", "web",
         "-f", "docker-compose.yml", "-f", "compose.chart-stream.yml",
         "config", "--no-env-resolution", "--format", "json"],
        cwd=root, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, "chart overlay must compile without operator env files"
    services = json.loads(result.stdout)["services"]
    q = services["openbq-kdb"]
    assert not q.get("ports")
    assert q["networks"] == {"live-private": None}
    assert q["command"][-2:] == ["--data-dir", "/data"]
    assert "--mode" in q["command"] and "tickplant" in q["command"]
    assert q["read_only"] is True
    for service, identity in (("live-grid", "live-grid"), ("eod-dump", "eod-export")):
        client = services[service]
        assert client["environment"]["KDB_USERNAME"] == identity
        assert client["environment"]["KDB_PASSWORD_FILE"].startswith("/run/secrets/")
        assert all(volume.get("read_only") for volume in client["volumes"]
                   if volume["target"].startswith("/run/secrets/"))
    assert services["live-grid"]["environment"]["LIVE_GRID_CHART_STREAM"] == "true"
