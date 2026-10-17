# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the API's /providers.json builder (lanes/openbq_lanes.py), the
inventory key-maint joins its rows against."""
import os
import sys
from pathlib import Path

os.environ["OPENBQ_ROLE"] = "worker"  # importing the module must not spawn the production lane
sys.path.insert(0, str(Path(__file__).parents[2] / "lanes"))
from openbq_lanes import provider_descriptor as build_provider_descriptor


def test_provider_with_credentials_is_required():
    out = build_provider_descriptor({"fmp": ["fmp_api_key"]})
    assert out[0]["auth"] == "required"


def test_cftc_and_econdb_with_credentials_are_optional():
    out = build_provider_descriptor({"cftc": ["cftc_app_token"], "econdb": ["econdb_api_key"]})
    by_id = {p["id"]: p for p in out}
    assert by_id["cftc"]["auth"] == "optional"
    assert by_id["econdb"]["auth"] == "optional"


def test_bls_with_credentials_is_required_not_optional():
    out = build_provider_descriptor({"bls": ["bls_api_key"]})
    assert out[0]["auth"] == "required"


def test_provider_with_no_credentials_is_not_required():
    out = build_provider_descriptor({"yfinance": []})
    assert out[0]["auth"] == "not_required"


def test_deltalake_is_local_others_are_not():
    out = build_provider_descriptor({"deltalake": ["s3_endpoint"], "fmp": ["fmp_api_key"]})
    by_id = {p["id"]: p for p in out}
    assert by_id["deltalake"]["local"] is True
    assert by_id["fmp"]["local"] is False


def test_env_vars_are_upper_cased():
    out = build_provider_descriptor({"fmp": ["fmp_api_key"]})
    assert out[0]["env_vars"] == ["FMP_API_KEY"]


def test_unknown_provider_id_gets_title_cased_fallback_name():
    out = build_provider_descriptor({"some_new_provider": []})
    assert out[0]["name"] == "Some New Provider"


def test_output_is_sorted_by_id():
    out = build_provider_descriptor({"fmp": [], "cftc": [], "bls": []})
    assert [p["id"] for p in out] == ["bls", "cftc", "fmp"]
