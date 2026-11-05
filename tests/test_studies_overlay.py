# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""v12/compose.studies.yaml: one studies volume, written by arts-charts, read by live-grid
(spec 2026-11-04 §2). An overlay, so the charts profile and the live profile are unchanged."""
import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = yaml.safe_load((ROOT / "v12/compose.studies.yaml").read_text())


def test_arts_charts_writes_and_live_grid_reads_one_volume():
    services = OVERLAY["services"]
    assert services["arts-charts"]["volumes"] == ["ta-studies:/studies"]
    assert services["live-grid"]["volumes"] == ["ta-studies:/studies:ro"]
    for name in ("arts-charts", "live-grid"):
        assert services[name]["environment"]["TA_STUDIES_DIR"] == "/studies"
    assert set(services) == {"arts-charts", "live-grid"}
    assert list(OVERLAY["volumes"]) == ["ta-studies"]


def test_the_management_route_stays_off_by_default():
    assert "TA_STUDIES_API" not in OVERLAY["services"]["arts-charts"]["environment"]


def test_both_images_own_the_mount_point():
    for dockerfile in ("v12/arts-charts/Dockerfile", "live-grid/Dockerfile"):
        assert "install -d -o 10001 -g 10001 /studies" in (ROOT / dockerfile).read_text(), dockerfile


def test_the_arts_charts_image_installs_the_engine_from_this_repository():
    charts = yaml.safe_load((ROOT / "v12/compose.charts.yaml").read_text())
    build = charts["x-arts-charts"]["build"]
    assert build["additional_contexts"] == {"openbq-ta": "./live-grid/openbq-ta"}
    assert "COPY --from=openbq-ta" in (ROOT / "v12/arts-charts/Dockerfile").read_text()


def test_verify_fails_naming_both_versions_when_the_engines_differ():
    # verify_charts.py runs against live containers, so lift its pure comparison out of the source.
    tree = ast.parse((ROOT / "v12/verify/verify_charts.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "one_engine")
    ns = {}
    exec(compile(ast.Module([fn], []), "verify_charts.py", "exec"), ns)
    name, ok = ns["one_engine"]("0.1.0", "0.1.1")
    assert not ok and "0.1.0" in name and "0.1.1" in name
    assert ns["one_engine"]("0.1.0", "0.1.0")[1]
    assert not ns["one_engine"](None, None)[1]
