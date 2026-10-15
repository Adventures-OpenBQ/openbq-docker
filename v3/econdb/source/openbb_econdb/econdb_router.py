# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""EconDB router: /api/v1/econdb/economy/{indicators,available_indicators,country_profile}.

openbb-core 2 mounts each provider's commands under its own namespace (as
openbb_nasdaq does for /nasdaq/economy/calendar); the shared ODP 4 economy
router that once served EconDB is not installed. The widget ids follow:
econdb_economy_indicators_econdb_obb, econdb_economy_available_indicators_econdb_obb
and econdb_economy_country_profile_econdb_obb. Each route's model is the
econdb-only EconDb<Std> key (openbb_econdb/__init__.py), so econdb is its only
provider. No key: the provider asks EconDB for a temporary token when none is set.
"""
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import ExtraParams, ProviderChoices, StandardParams
from openbb_core.app.query import Query
from openbb_core.app.router import Router

router = Router(prefix="", description="EconDB economic data.")
economy = Router(prefix="/economy", description="EconDB economic data.")


@economy.command(
    model="EconDbEconomicIndicators",
    examples=[APIEx(parameters={"provider": "econdb", "symbol": "RGDP", "country": "US"})],
)
async def indicators(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Economic indicators by country and indicator symbol (RGDP, CPI, URATE, ... or main)."""
    return await OBBject.from_query(Query(**locals()))


@economy.command(model="EconDbAvailableIndicators", examples=[APIEx(parameters={"provider": "econdb"})])
async def available_indicators(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """The indicator symbols and countries EconDB serves."""
    return await OBBject.from_query(Query(**locals()))


@economy.command(
    model="EconDbCountryProfile",
    examples=[APIEx(parameters={"provider": "econdb", "country": "united_states"})],
)
async def country_profile(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """A country's main economic figures."""
    return await OBBject.from_query(Query(**locals()))


router.include_router(economy)
