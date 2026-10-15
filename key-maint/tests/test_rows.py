# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

from app.rows import build_rows, build_summary

VALUES = dict(EODHD_API_KEY="demo", FMP_API_KEY="realkey99", FRED_API_KEY="")

DESC = [
    {"id": "yfinance", "name": "Yahoo Finance", "credentials": [], "env_vars": [],
     "auth": "not_required", "local": False},
    {"id": "fmp", "name": "FMP", "credentials": ["fmp_api_key"], "env_vars": ["FMP_API_KEY"],
     "auth": "required", "local": False},
    {"id": "bls", "name": "BLS", "credentials": ["bls_api_key"], "env_vars": ["BLS_API_KEY"],
     "auth": "optional", "local": False},
    {"id": "kdb", "name": "kdb+", "credentials": [], "env_vars": [],
     "auth": "not_required", "local": True},
]


def row(rows, env_var):
    return next(r for r in rows if r.get("env_var") == env_var)


def prow(rows, provider_id):
    return next(r for r in rows if r.get("provider_id") == provider_id)


class TestStatus:
    def test_set_empty_missing(self):
        rows = build_rows(VALUES, tier=1, tests=None)
        assert row(rows, "FMP_API_KEY")["status"] == "set"
        assert row(rows, "FRED_API_KEY")["status"] == "empty"
        assert row(rows, "BLS_API_KEY")["status"] == "missing"

    def test_demo_flagged(self):
        rows = build_rows(VALUES, tier=1, tests=None)
        assert row(rows, "EODHD_API_KEY")["demo"] is True
        assert row(rows, "FMP_API_KEY")["demo"] is False

    def test_ignored_vars_absent(self):
        rows = build_rows({"KDB_HOST": "x"}, tier=1, tests=None)
        assert not any(r.get("env_var") == "KDB_HOST" for r in rows)

    def test_unregistered_credential_var_gets_generic_row(self):
        rows = build_rows(dict(NEWTHING_API_KEY="v"), tier=1, tests=None)
        r = row(rows, "NEWTHING_API_KEY")
        assert r["provider"] == "NEWTHING_API_KEY"
        assert r["status"] == "set"


class TestTierRedaction:
    def test_value_absent_below_tier_3(self):
        for tier in (1, 2):
            for r in build_rows(VALUES, tier=tier, tests=None):
                assert "value" not in r

    def test_value_present_at_tier_3(self):
        rows = build_rows(VALUES, tier=3, tests=None)
        assert row(rows, "FMP_API_KEY")["value"] == "realkey99"


class TestTests:
    def test_test_field_attached(self):
        tests = {"fmp": [{"result": "ok", "detail": "HTTP 200", "kind": "credential",
                          "code": None, "checked_at": "2026-09-24T00:00:00Z"}]}
        rows = build_rows(VALUES, tier=2, tests=tests)
        assert row(rows, "FMP_API_KEY")["test"]["result"] == "ok"
        assert row(rows, "FMP_API_KEY")["checks"][0]["result"] == "ok"

    def test_no_tests_no_field(self):
        rows = build_rows(VALUES, tier=2, tests=None)
        assert "test" not in row(rows, "FMP_API_KEY")


class TestJoinRegistered:
    # Case A: descriptor provider WITH a registry entry.
    def test_registered_provider_gets_provider_id_auth_supported(self):
        rows = build_rows(dict(FMP_API_KEY="k"), tier=1, tests=None, descriptor=DESC)
        r = prow(rows, "fmp")
        assert r["env_var"] == "FMP_API_KEY"
        assert r["auth"] == "required"
        assert r["supported"] is True
        assert r["status"] == "set"


class TestJoinKeyless:
    # Case B: descriptor provider WITHOUT a registry entry (keyless).
    def test_keyless_provider_row_has_no_value_and_no_env_var(self):
        rows = build_rows({}, tier=3, tests=None, descriptor=DESC)
        r = prow(rows, "yfinance")
        assert r["provider"] == "Yahoo Finance"
        assert r["env_var"] == ""
        assert r["auth"] == "not_required"
        assert r["supported"] is True
        assert r["status"] == "missing"
        assert "value" not in r  # keyless rows NEVER carry a value, even at tier 3


class TestJoinLocalExcluded:
    def test_local_providers_are_omitted(self):
        rows = build_rows({}, tier=1, tests=None, descriptor=DESC)
        assert all(r.get("provider_id") != "kdb" for r in rows)


class TestJoinNotInstalled:
    # Case C: a registry entry the descriptor lacks.
    def test_registry_only_provider_is_supported_false_not_installed(self):
        rows = build_rows(dict(NASDAQ_API_KEY="k"), tier=1, tests=None, descriptor=DESC)
        r = prow(rows, "nasdaq")
        assert r["supported"] is False
        assert r["auth"] == "required"
        assert r["test"] == {
            "result": "skipped", "detail": "not installed on this backend",
            "kind": "connectivity", "code": "not_installed",
        }

    def test_not_installed_row_is_never_probed(self):
        # Even if a (stray) check were supplied for it, the fixed skipped test wins.
        rows = build_rows({}, tier=1, tests={"nasdaq": [{"result": "ok"}]}, descriptor=DESC)
        assert prow(rows, "nasdaq")["test"]["code"] == "not_installed"


class TestOrdering:
    def test_descriptor_order_then_registry_only(self):
        rows = build_rows({}, tier=1, tests=None, descriptor=DESC)
        ids = [r.get("provider_id") for r in rows if r.get("provider_id")]
        # yfinance, fmp, bls (descriptor, non-local, in order) precede nasdaq (registry-only)
        assert ids.index("yfinance") < ids.index("fmp") < ids.index("bls")
        assert ids.index("bls") < ids.index("nasdaq")


class TestDescriptorUnavailable:
    def test_descriptor_unavailable_falls_back_to_registry_rows(self):
        rows = build_rows(dict(FMP_API_KEY="k"), tier=1, tests=None, descriptor=None)
        r = row(rows, "FMP_API_KEY")
        assert r["provider_id"] == "fmp"
        assert r["auth"] == "required"
        assert "supported" not in r
        # optional providers still read "optional" from the registry fallback;
        # bls is NOT in that set (it 400s without a key) so it reads "required"
        assert row(rows, "BLS_API_KEY")["auth"] == "required"

    def test_summary_banner_when_descriptor_unavailable(self):
        rows = build_rows(dict(FMP_API_KEY="k"), tier=1, tests=None, descriptor=None)
        summary = build_summary(rows, descriptor_available=False)
        assert summary.splitlines()[0] == (
            "Provider inventory unavailable; showing configured credentials only."
        )

    def test_descriptor_entry_missing_keys_does_not_crash(self):
        bad = [{"id": "fmp"}]  # no env_vars / auth / local
        rows = build_rows({}, tier=1, tests=None, descriptor=bad)
        r = prow(rows, "fmp")
        assert r["supported"] is True
        assert r["auth"] == "unknown"  # missing auth degrades to "unknown", never crashes


class TestChecksAttach:
    def test_worst_check_and_checks_list_attached(self):
        checks = {"fmp": [
            {"result": "ok", "detail": "HTTP 200", "kind": "connectivity", "code": None,
             "checked_at": "2026-09-24T00:00:00Z"},
            {"result": "auth_failed", "detail": "x", "kind": "credential", "code": "http_auth",
             "checked_at": "2026-09-24T00:00:00Z"},
        ]}
        rows = build_rows(dict(FMP_API_KEY="k"), tier=1, tests=checks, descriptor=DESC)
        r = prow(rows, "fmp")
        assert r["test"]["result"] == "auth_failed"        # worst of the two
        assert [c["result"] for c in r["checks"]] == ["ok", "auth_failed"]


class TestDegradation:
    def test_missing_file_yields_banner_and_unknown_rows(self):
        rows = build_rows(None, tier=2, tests=None)
        assert rows[0]["provider"] == "⚠ credentials.env"
        assert rows[0]["status"] == "unknown"
        assert all(r["status"] == "unknown" for r in rows[1:])


class TestMalformed:
    def test_malformed_entries_produce_trailing_warning_rows(self):
        rows = build_rows(VALUES, tier=3, tests=None, malformed=["line 7"])
        assert rows[-1] == {
            "provider": "⚠ malformed line",
            "env_var": "line 7",
            "status": "unknown",
            "demo": False,
        }
        assert "value" not in rows[-1]


class TestSummary:
    def test_never_renders_a_credential_value(self):
        """The reason this widget declares no raw view.

        At tier 3 build_rows() puts the credential itself in row["value"].
        The summary is built from those rows, so a careless f-string here
        would publish every key to any dashboard that adds the widget.
        """
        # Distinctive values on purpose. The shared VALUES fixture sets EODHD
        # to the literal string "demo", which collides with the summary's own
        # "Public demo key" line and would fail this assertion without a leak.
        secrets = dict(EODHD_API_KEY="SECRET-eodhd-a1b2c3", FMP_API_KEY="SECRET-fmp-d4e5f6")
        rows = build_rows(secrets, tier=3, tests=None)
        assert any("value" in r for r in rows), "tier 3 should carry values"
        summary = build_summary(rows)
        for secret in secrets.values():
            assert secret not in summary

    def test_counts_and_names_the_missing(self):
        summary = build_summary(build_rows(VALUES, tier=1, tests=None))
        assert "Missing" in summary
        # FRED is present but blank -- that is "empty", not "missing".
        assert "Present but empty" in summary

    def test_flags_a_public_demo_key(self):
        summary = build_summary(build_rows(VALUES, tier=1, tests=None))
        assert "Public demo key" in summary

    def test_unreadable_credentials_file_is_reported(self):
        summary = build_summary(build_rows(None, tier=1, tests=None))
        assert "Unreadable" in summary

    def test_all_private_keys_says_so(self):
        from app.registry import PROVIDERS

        every = {var: "private-value" for var in PROVIDERS}
        summary = build_summary(build_rows(every, tier=1, tests=None))
        assert "Every provider is configured" in summary
        assert "private-value" not in summary
