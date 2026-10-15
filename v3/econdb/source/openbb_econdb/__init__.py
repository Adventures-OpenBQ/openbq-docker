# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB) at 174d7e69,
# Copyright (c) 2021-2023 OpenBB Inc., licensed under the MIT License (see LICENSE).
# Modifications Copyright 2026 SecretoftheUniverse.com LLC, Apache-2.0 (see NOTICE).
"""EconDB provider module."""

from openbb_core.provider.abstract.provider import Provider
from openbb_econdb.models.available_indicators import EconDbAvailableIndicatorsFetcher
from openbb_econdb.models.country_profile import EconDbCountryProfileFetcher
from openbb_econdb.models.economic_indicators import EconDbEconomicIndicatorsFetcher

econdb_provider = Provider(
    name="EconDB",
    website="https://econdb.com",
    description="""The mission of the company is to process information in ways that
facilitate understanding of the economic situation at different granularity levels.

The sources of data include official statistics agencies and so-called alternative
data sources where we collect direct observations of the market and generate
aggregate statistics.""",
    credentials=[
        "api_key"
    ],  # Can be left as None, an attempt to use a temporary token will be made.
    fetcher_dict={
        "AvailableIndicators": EconDbAvailableIndicatorsFetcher,
        "CountryProfile": EconDbCountryProfileFetcher,
        "EconomicIndicators": EconDbEconomicIndicatorsFetcher,
    },
    repr_name="EconDB",
)

# openbq: every fetcher also under an econdb-only model key EconDb<Std>, which the
# routes in econdb_router.py use, so their only provider is econdb even when another
# extension (openbq-eodhd on v9) implements the same standard model.
for _std_key, _fetcher in list(econdb_provider.fetcher_dict.items()):
    econdb_provider.fetcher_dict[f"EconDb{_std_key}"] = _fetcher
