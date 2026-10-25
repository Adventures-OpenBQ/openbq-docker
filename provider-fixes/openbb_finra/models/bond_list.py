# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB),
# Copyright (c) 2021-2026 OpenBB Inc., licensed under the Apache License, Version 2.0.
# Modifications Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""FINRA Bond List Model."""

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finra.models.bond_prices import FinraBondPricesData
from openbb_finra.utils.constants import BondTypes

# OpenBQ row cap: uncapped MBS is 1.5M rows, a 2 GB response and ~11-12 GB of server
# memory. The cap bounds TRACE paging itself (max_rows); TRACE sorts by FINRA
# security id, so a capped list is the first N bonds in id order, not a sample.
ROW_CAPS: dict[str, int] = {"MBS": 250_000}


class FinraBondListQueryParams(QueryParams):
    """FINRA Bond List Query."""

    # OpenBQ default: TS (~60 KB). CA built a 150 MB response and held ~1.5 GB of
    # server memory; every type stays selectable.
    bond_type: BondTypes = Field(
        default="TS",
        description="The TRACE product - CA (corporate and agency), TS (U.S. Treasury),"
        + " TBA, MBS, ABS, or CMO.",
    )
    include_matured: bool = Field(
        default=False, description="Include the bonds that have matured."
    )


class FinraBondListData(FinraBondPricesData):
    """FINRA Bond List Data."""


class FinraBondListFetcher(Fetcher[FinraBondListQueryParams, list[FinraBondListData]]):
    """Transform the query, extract and transform the data from FINRA TRACE."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinraBondListQueryParams:
        """Transform the query."""
        return FinraBondListQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinraBondListQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return every TRACE-reported bond of one type.

        Raises
        ------
        EmptyDataError
            If TRACE holds no bond of the type.
        """
        from openbb_finra.models.bond_prices import (
            FinraBondPricesQueryParams,
            distinct_bonds,
            read_bonds,
        )
        from openbb_finra.utils.client import trace_session

        cap = ROW_CAPS.get(query.bond_type)
        filters = FinraBondPricesQueryParams(
            bond_type=query.bond_type, include_matured=query.include_matured, limit=cap
        )

        async with trace_session() as trace:
            rows = await read_bonds(trace, filters, query.bond_type, [])

        if cap and len(rows) >= cap:
            from warnings import warn

            from openbb_core.app.model.abstract.warning import OpenBBWarning

            warn(
                f"{query.bond_type} is capped at the first {cap:,} TRACE records"
                + " (by FINRA security id).",
                OpenBBWarning,
            )

        values = distinct_bonds([rows])

        if not values:
            raise EmptyDataError(f"TRACE holds no {query.bond_type} bonds.")

        return values

    @staticmethod
    def transform_data(
        query: FinraBondListQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FinraBondListData]:
        """Transform the data to the model."""
        return [FinraBondListData.model_validate(record) for record in data]
