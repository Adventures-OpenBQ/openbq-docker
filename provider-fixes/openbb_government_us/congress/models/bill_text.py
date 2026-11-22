"""Congress Gov Bills Text Model."""

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class CongressBillTextQueryParams(QueryParams):
    """Congress Gov Bills Text Query."""

    __json_schema_extra__ = {
        "urls": {
            "multiple_items_allowed": True,
        }
    }
    urls: str | list[str] | dict[str, list[str]] = Field(
        description="List of direct bill URLs to download.",
        kw_only=True,
    )


class CongressBillTextData(Data):
    """Congress Gov Bills Text Data."""

    error_type: str | None = Field(
        default=None,
        description="Error type if any error occurs during the download.",
    )
    content: str = Field(
        description="Base64-encoded PDF document.",
    )
    filename: str | None = Field(
        default=None,
        description="The filename of the downloaded PDF.",
    )
    data_format: dict[str, str] | None = Field(
        default=None,
        description="Data format information, including data type and filename.",
    )


class CongressBillTextFetcher(
    Fetcher[CongressBillTextQueryParams, list[CongressBillTextData]]
):
    """Congress Gov Bills Text Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> CongressBillTextQueryParams:
        """Transform the query parameters."""

        return CongressBillTextQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CongressBillTextQueryParams,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list:
        """Extract data from the query."""
        import base64  # noqa
        from io import BytesIO
        from urllib.parse import urlsplit
        from openbb_core.provider.utils.helpers import make_request

        urls = (
            query.urls.get("urls", [])
            if isinstance(query.urls, dict)
            else (query.urls if isinstance(query.urls, list) else query.urls.split(","))
        )
        results: list = []

        for url in urls:
            filename = url.rsplit("/", 1)[-1]
            try:
                parsed = urlsplit(url)
                valid = (
                    parsed.scheme == "https"
                    and parsed.hostname in {"congress.gov", "www.congress.gov", "govinfo.gov", "www.govinfo.gov"}
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.port in (None, 443)
                )
                filename = parsed.path.rsplit("/", 1)[-1]
            except ValueError:
                valid = False
            if not valid:
                results.append(
                    {
                        "error_type": "invalid_url",
                        "content": f"Invalid URL: {url}. Must be a valid Congress.gov or GovInfo URL.",
                        "filename": filename,
                    }
                )
                continue
            try:
                response = make_request(url, allow_redirects=False)
                response.raise_for_status()
                if not 200 <= response.status_code < 300:
                    raise ValueError("The document download did not return a successful HTTP response.")
                datatype = filename.split(".")[-1].lower()

                if datatype == "pdf":
                    if not response.content.startswith(b"%PDF-") or b"%%EOF" not in response.content[-2048:]:
                        raise ValueError("The document download did not return a complete PDF.")
                    pdf_content = base64.b64encode(
                        BytesIO(response.content).read()
                    ).decode("utf-8")
                    results.append(
                        {
                            "content": pdf_content,
                            "data_format": {
                                "data_type": "pdf",
                                "filename": filename,
                            },
                        }
                    )
                else:
                    results.append(
                        {
                            "content": response.text,
                            "data_format": {
                                "data_type": "text",
                                "filename": filename,
                            },
                        }
                    )
            except Exception as exc:
                results.append(
                    {
                        "error_type": "download_error",
                        "content": f"{exc.__class__.__name__}: {exc.args[0]}",
                        "filename": url.split("/")[-1],
                    }
                )
                continue

        return results

    @staticmethod
    def transform_data(
        query: CongressBillTextQueryParams,
        data: list,
        **kwargs: Any,
    ) -> list[CongressBillTextData]:
        """Transform the extracted data into the desired format."""
        return [CongressBillTextData(**item) for item in data]
