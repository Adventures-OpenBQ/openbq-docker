# SPDX-License-Identifier: Apache-2.0
"""Small real-identifier cases; mutations exercise rejection, not demo data."""

import importlib.util
from pathlib import Path
import pytest


def implementation():
    p = Path(__file__).resolve().parents[1] / "v11/build_sp500_security_master.py"
    spec = importlib.util.spec_from_file_location("sp500_bootstrap", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs():
    components = [
        {
            "Code": "GOOG",
            "Exchange": "US",
            "Name": "Alphabet Class C",
            "Sector": "Communication Services",
            "Industry": "Internet",
            "Weight": "0.02",
        },
        {
            "Code": "GOOGL",
            "Exchange": "US",
            "Name": "Alphabet Class A",
            "Sector": "Communication Services",
            "Industry": "Internet",
            "Weight": "0.02",
        },
    ]
    symbols = [
        {
            "Code": "GOOG",
            "Exchange": "NASDAQ",
            "Currency": "USD",
            "Country": "USA",
            "Type": "Common Stock",
            "Isin": "US02079K1079",
        },
        {
            "Code": "GOOGL",
            "Exchange": "NASDAQ",
            "Currency": "USD",
            "Country": "USA",
            "Type": "Common Stock",
            "Isin": "US02079K3059",
        },
    ]
    wiki = [
        [
            "GOOG",
            "Alphabet Class C",
            "Communication Services",
            "Interactive Media & Services",
            "US",
            "2014-04-03",
            "1652044",
            "1998",
        ],
        [
            "GOOGL",
            "Alphabet Class A",
            "Communication Services",
            "Interactive Media & Services",
            "US",
            "2006-04-03",
            "1652044",
            "1998",
        ],
    ]
    return components, symbols, wiki


def test_share_classes_are_securities_not_duplicate_issuers():
    module = implementation()
    tables = module.normalize(*inputs())
    assert len(tables["issuers"]) == 1
    assert len(tables["securities"]) == 2
    assert len(tables["memberships"]) == 2
    assert len({r["security_id"] for r in tables["securities"]}) == 2
    assert tables["issuers"][0]["cik"] == "0001652044"
    assert {r["taxonomy"] for r in tables["classifications"]} == {
        "eodhd",
        "GICS_reported_by_Wikipedia",
    }
    assert all(r["effective_from"] is None for r in tables["memberships"])


def test_missing_metadata_does_not_drop_a_constituent():
    module = implementation()
    c, s, w = inputs()
    tables = module.normalize(c, s[:1], w)
    assert len(tables["memberships"]) == 2
    assert any(r["code"] == "MISSING_LISTING_REFERENCE" for r in tables["issues"])


def test_invalid_isin_not_promoted_to_verified_identifier():
    module = implementation()
    c, s, w = inputs()
    s[0]["Isin"] = "US02079K1070"
    tables = module.normalize(c, s, w)
    assert any(r["code"] == "INVALID_ISIN" for r in tables["issues"])
    assert (
        next(r for r in tables["securities"] if r["symbol"] == "GOOG")["isin"] is None
    )


def test_duplicate_constituent_is_refused():
    module = implementation()
    c, s, w = inputs()
    with pytest.raises(ValueError):
        module.normalize(c + [c[0]], s, w)


def test_current_provider_cik_is_primary_and_conflict_is_visible():
    module = implementation()
    c, s, w = inputs()
    rows = module.normalize(c, s, w, {"GOOG": {"Code": "GOOG", "CIK": "1234567"}})
    goog = next(row for row in rows["securities"] if row["symbol"] == "GOOG")
    issuer = next(
        row for row in rows["issuers"] if row["issuer_id"] == goog["issuer_id"]
    )
    assert issuer["cik"] == "0001234567"
    assert issuer["source_ref"] == "general-GOOG"
    assert any(row["code"] == "CIK_CONFLICT" for row in rows["issues"])


def test_provider_gics_is_separate_from_community_classification():
    module = implementation()
    rows = module.normalize(
        *inputs(), {"GOOG": {"Code": "GOOG", "GicSector": "Communication Services"}}
    )
    assert any(
        row["taxonomy"] == "GICS_reported_by_EODHD"
        and row["source_ref"] == "general-GOOG"
        for row in rows["classifications"]
    )


def test_source_metadata_cannot_export_provider_credentials():
    module = implementation()
    for source in [
        {"url": "https://example.test/api?api_token=private", "parameters": {}},
        {"url": "https://user:private@example.test/api", "parameters": {}},
        {"url": "https://example.test/api", "parameters": {"api_token": ""}},
    ]:
        with pytest.raises(ValueError, match="credential"):
            module.validate_source_metadata(source)


def test_sec_ticker_evidence_resolves_a_provider_cik_conflict():
    module = implementation()
    sec = {
        "0001652044": {
            "cik": "1652044",
            "name": "Alphabet Inc.",
            "tickers": ["GOOG", "GOOGL"],
            "sic": "7370",
            "sicDescription": "Services",
        }
    }
    rows = module.normalize(
        *inputs(), {"GOOG": {"Code": "GOOG", "CIK": "1234567"}}, sec
    )
    goog = next(row for row in rows["securities"] if row["symbol"] == "GOOG")
    issuer = next(
        row for row in rows["issuers"] if row["issuer_id"] == goog["issuer_id"]
    )
    assert issuer["cik"] == "0001652044"
    assert issuer["source_ref"] == "sec-0001652044"
    assert issuer["verification"] == "SEC_ticker_match"
    assert any(row["code"] == "CIK_RECONCILED_WITH_SEC" for row in rows["issues"])


def test_sec_cik_without_matching_ticker_is_not_claimed_verified():
    module = implementation()
    sec = {"0001652044": {"cik": "1652044", "name": "Unrelated", "tickers": ["OTHER"]}}
    rows = module.normalize(*inputs(), None, sec)
    assert all(row["verification"] != "SEC_ticker_match" for row in rows["issuers"])
