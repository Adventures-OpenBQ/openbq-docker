# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for the API's /providers.json builder (lanes/openbq_lanes.py), the
inventory key-maint joins its rows against."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

from app.probes import run_probes

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


def test_bls_with_credentials_is_optional():
    out = build_provider_descriptor({"bls": ["bls_api_key"]})
    assert out[0]["auth"] == "optional"


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


def test_bls_bulk_probe_uses_the_backend_example_without_a_key():
    def vendor(request):
        pytest.fail("the keyless probe must not call the vendor directly")

    def backend(request):
        assert request.url.path == "/api/v1/bls/series"
        assert dict(request.url.params) == {"provider": "bls", "symbol": "CUUR0000SA0"}
        return httpx.Response(200, json={"results": [{"value": 1}]})

    async def go():
        descriptor = build_provider_descriptor({"bls": ["bls_api_key"]})
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(vendor)) as cc,
            httpx.AsyncClient(transport=httpx.MockTransport(backend)) as ac,
        ):
            return await run_probes({}, descriptor, "http://api", None, cred_client=cc, api_client=ac)

    checks = asyncio.run(go())["bls"]
    assert [(c.kind, c.result) for c in checks] == [("connectivity", "ok")]
