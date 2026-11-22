# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import pytest
import polars as pl
from openbq_ta.registry import get, resolve, StudyError
from openbq_ta import studies


def test_builtin_catalog_has_shared_typed_defaults_and_versions():
    from openbq_ta.registry import catalog, catalog_entry

    entries = {entry["name"]: entry for entry in catalog()}
    assert entries["rsi"]["param_schema"]["period"] == {
        "type": "integer",
        "default": 14,
        "label": "Period",
        "minimum": 1,
        "step": 1,
    }
    assert entries["stoch"]["params"]["smooth_k"] == 1
    assert len(entries["rsi"]["definition_version"]) == 64
    assert catalog_entry("rsi") == entries["rsi"]
    assert entries["avwap"]["param_schema"]["anchor"]["default"] is None


def test_custom_schema_shared_validation_and_definition_identity():
    from openbq_ta.registry import catalog_entry

    try:

        @studies.study(
            name="typed_custom",
            label="Typed",
            params={"length": 2, "factor": 1.5, "enabled": True, "mode": "close"},
            colors={"answer": "#fff"},
            param_schema={
                "length": {"type": "integer", "minimum": 1, "maximum": 40, "label": "Length"},
                "factor": {"type": "number", "minimum": 0.5, "step": 0.25},
                "enabled": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["close", "open"]},
            },
        )
        def typed(p):
            return [(pl.col(p["mode"]) * p["factor"]).alias("answer")]

        descriptor = catalog_entry("typed_custom")
        assert descriptor["param_schema"]["length"]["default"] == 2
        assert resolve("typed_custom", length=4, enabled=False, mode="open").params["length"] == 4
        for overrides in [
            {"length": True},
            {"length": 2.5},
            {"length": 0},
            {"length": 41},
            {"enabled": 1},
            {"mode": "high"},
            {"factor": float("nan")},
            {"unknown": 2},
        ]:
            with pytest.raises(ValueError):
                resolve("typed_custom", **overrides)
        version = descriptor["definition_version"]
        assert catalog_entry("typed_custom")["definition_version"] == version
    finally:
        studies.unload("<runtime>")


@pytest.mark.parametrize(
    "schema",
    [
        {"n": {"type": "integer", "default": 3}},
        {"n": {"type": "integer", "minimum": 4}},
        {"missing": {"type": "number"}},
        {"n": {"type": "integer", "step": 0}},
    ],
)
def test_registration_rejects_inconsistent_schema_defaults(schema):
    with pytest.raises(StudyError):

        @studies.study(
            name="invalid_schema",
            label="Invalid",
            params={"n": 2},
            colors={"x": "#fff"},
            param_schema=schema,
        )
        def invalid(p):
            return [pl.col("close").alias("x")]


def test_resolve_rejects_invalid_builtin_types_and_keeps_time_values():
    from datetime import datetime, timezone

    for value in [0, -1, True, 1.2, "14"]:
        with pytest.raises(ValueError):
            resolve("rsi", period=value)
    moment = datetime(2026, 11, 22, tzinfo=timezone.utc)
    assert resolve("avwap", anchor=moment).params["anchor"] == moment
    assert resolve("avwap").params["anchor"] is None


def test_operator_module_global_edit_changes_definition_version(tmp_path):
    from openbq_ta.registry import catalog_entry

    template = """import polars as pl
from openbq_ta.studies import study
SCALE = {scale}
@study(name="global_version",label="Global",params={{}},colors={{"x":"#fff"}})
def custom(p): return [(pl.col("close") * SCALE).alias("x")]
"""
    path = tmp_path / "global_fixture.py"
    try:
        path.write_text(template.format(scale=1))
        studies.load_file(path)
        before = catalog_entry("global_version")["definition_version"]
        path.write_text(template.format(scale=2))
        studies.load_file(path)
        assert catalog_entry("global_version")["definition_version"] != before
        import sys

        assert sys.modules["ta_custom_global_fixture"].SCALE == 2
    finally:
        studies.unload("global_fixture")
