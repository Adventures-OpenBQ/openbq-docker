# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from app.credfile import parse_text
from app.registry import IGNORE, PROVIDERS, is_demo

_EIA_DEMO_KEY = "DEMO_KEY"

EXAMPLE = Path(__file__).resolve().parents[2] / "credentials.env.example"


class TestCoverage:
    def test_every_example_var_is_registered_or_ignored(self):
        """Registry and credentials.env.example may not drift."""
        example_vars = set(parse_text(EXAMPLE.read_text()).keys())
        covered = set(PROVIDERS) | set(IGNORE)
        assert example_vars <= covered, f"unregistered: {example_vars - covered}"

    def test_no_var_is_both_registered_and_ignored(self):
        assert not (set(PROVIDERS) & set(IGNORE))

    def test_registry_keys_match_env_var_field(self):
        for var, p in PROVIDERS.items():
            assert p.env_var == var


class TestDemo:
    def test_eodhd_demo_key(self):
        assert is_demo("EODHD_API_KEY", "demo") is True
        assert is_demo("EODHD_API_KEY", "DEMO") is True  # case-insensitive

    def test_real_key_not_demo(self):
        assert is_demo("EODHD_API_KEY", "abc123realkey") is False

    def test_unknown_var_never_demo(self):
        assert is_demo("SOMETHING_API_KEY", "demo") is False

    def test_fmp_demo_is_retired(self):
        # v3.0.1: FMP's "demo" key is dead (401 Invalid API KEY); the badge
        # must not claim it is a demo value any more.
        assert is_demo("FMP_API_KEY", "demo") is False

    def test_eia_demo_key(self):
        assert is_demo("EIA_API_KEY", _EIA_DEMO_KEY) is True
        assert is_demo("EIA_API_KEY", "demo_key") is True  # case-insensitive
        assert is_demo("EIA_API_KEY", "realkey") is False

    def test_congress_gov_demo_key(self):
        assert is_demo("CONGRESS_GOV_API_KEY", _EIA_DEMO_KEY) is True
        assert is_demo("CONGRESS_GOV_API_KEY", "realkey") is False

    def test_alpha_vantage_demo_key_unchanged(self):
        assert is_demo("ALPHA_VANTAGE_API_KEY", "demo") is True


class TestProbes:
    def test_congress_probe_built_with_key(self):
        from app.registry import PROVIDERS

        req = PROVIDERS["CONGRESS_GOV_API_KEY"].probe.build(dict(CONGRESS_GOV_API_KEY="mykey"))
        assert req is not None
        assert req.url.host == "api.congress.gov"
        assert "api_key=mykey" in str(req.url)

    def test_congress_probe_none_without_key(self):
        from app.registry import PROVIDERS

        assert PROVIDERS["CONGRESS_GOV_API_KEY"].probe.build({}) is None

    def test_congress_probe_invalid_marker(self):
        from app.registry import PROVIDERS

        assert PROVIDERS["CONGRESS_GOV_API_KEY"].probe.invalid_markers == ("API_KEY_INVALID",)

    def test_alpha_vantage_probe_uses_ibm(self):
        from app.registry import PROVIDERS

        req = PROVIDERS["ALPHA_VANTAGE_API_KEY"].probe.build(dict(ALPHA_VANTAGE_API_KEY="demo"))
        assert req is not None
        assert "symbol=IBM" in str(req.url)


class TestProviderId:
    def test_every_provider_has_a_provider_id(self):
        for p in PROVIDERS.values():
            assert p.provider_id and isinstance(p.provider_id, str)

    def test_alpaca_secret_shares_the_alpaca_id(self):
        assert PROVIDERS["ALPACA_API_KEY"].provider_id == "alpaca"
        assert PROVIDERS["ALPACA_API_SECRET"].provider_id == "alpaca"

    def test_provider_index_is_keyed_by_id(self):
        from app.registry import provider_index
        idx = provider_index()
        assert idx["fmp"].env_var == "FMP_API_KEY"
        assert idx["congress_gov"].env_var == "CONGRESS_GOV_API_KEY"


def test_eodhd_and_intrinio_probe_their_usage_endpoints():
    from app.registry import PROVIDERS

    e = PROVIDERS["EODHD_API_KEY"].probe.build({"EODHD_API_KEY": "YOUR_KEY"})
    assert str(e.url).startswith("https://eodhd.com/api/user?")
    i = PROVIDERS["INTRINIO_API_KEY"].probe.build({"INTRINIO_API_KEY": "YOUR_KEY"})
    assert str(i.url).startswith("https://api-v2.intrinio.com/account/current_usage?")
