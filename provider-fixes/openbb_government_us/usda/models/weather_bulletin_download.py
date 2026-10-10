# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB),
# Copyright (c) 2021-2026 OpenBB Inc., licensed under the Apache License, Version 2.0.
# Modifications Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Government US Weather Bulletin Download Model."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.weather_bulletin_download import (
    WeatherBulletinDownloadData,
    WeatherBulletinDownloadQueryParams,
)
from pydantic import Field, field_validator


class UsdaWeatherBulletinDownloadQueryParams(WeatherBulletinDownloadQueryParams):
    """US Government Weather Bulletin Download Query Params."""

    __json_schema_extra__ = {
        "urls": {
            "multiple_items_allowed": True,
        }
    }

    @field_validator("urls", mode="before", check_fields=False)
    @classmethod
    def _validate_urls(cls, v):
        """Read a null or missing selection as no URLs."""
        if isinstance(v, dict):
            v = v.get("urls")
        return [] if v is None else super()._validate_urls(v)


class UsdaWeatherBulletinDownloadData(WeatherBulletinDownloadData):
    """US Government Weather Bulletin Download Data."""

    data_format: dict[str, str] = Field(description="Data format information.")


class UsdaWeatherBulletinDownloadFetcher(
    Fetcher[
        UsdaWeatherBulletinDownloadQueryParams,
        list[UsdaWeatherBulletinDownloadData],
    ]
):
    """US Government Weather Bulletin Download Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> UsdaWeatherBulletinDownloadQueryParams:
        """Transform params into the query params model."""
        return UsdaWeatherBulletinDownloadQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: UsdaWeatherBulletinDownloadQueryParams,
        credentials: dict[str, Any] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the raw PDF content."""
        from openbb_core.provider.utils.helpers import get_async_requests_session

        results: dict = {}
        urls = query.urls

        for url in urls:
            if not url.lower().startswith("https://esmis.nal.usda.gov/"):
                raise OpenBBError(
                    ValueError(
                        f"Invalid URL '{url}'. Only URLs from 'esmis.nal.usda.gov' are supported."
                    )
                )
            if not url.lower().endswith(".pdf"):
                raise OpenBBError(
                    ValueError(
                        f"Invalid URL '{url}'. Only PDF documents are supported."
                    )
                )

        try:
            async with await get_async_requests_session() as session:
                session._max_field_size = 32768

                for url in urls:
                    async with await session.get(url) as response:
                        if response.status != 200:
                            raise OpenBBError(
                                ValueError(
                                    f"Failed to download document from {url}. Status code: {response.status}"
                                )
                            )
                        content_bytes = await response.read()
                        results[url] = content_bytes

            return results
        except Exception as e:
            raise OpenBBError(e) from e

    @staticmethod
    def transform_data(
        query: UsdaWeatherBulletinDownloadQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[UsdaWeatherBulletinDownloadData]:
        """Transform the raw PDF content into the data model."""
        import base64

        output: list[UsdaWeatherBulletinDownloadData] = []

        for url, content in data.items():
            content_b64 = base64.b64encode(content).decode("utf-8")
            data_format = {
                "data_type": "pdf",
                "filename": url.split("/")[-1],
            }
            bulletin_data = UsdaWeatherBulletinDownloadData(
                content=content_b64,
                data_format=data_format,
            )
            output.append(bulletin_data)

        return output
