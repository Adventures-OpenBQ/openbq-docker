# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB),
# Copyright (c) 2021-2026 OpenBB Inc., licensed under the Apache License, Version 2.0.
# Modifications Copyright 2026 SecretoftheUniverse.com LLC.
"""Documents handed to the Workspace file viewer."""

PDF_MAGIC = b"%PDF"
# The hosts TMX's filings (QuoteMedia) and index documents (S&P DJI) are served from.
DOCUMENT_HOSTS = ("app.quotemedia.com", "spindices.com", "us.spindices.com", "www.spglobal.com")


def _check_url(url: str) -> None:
    """Refuse a URL that is not https on a host TMX serves documents from."""
    from urllib.parse import urlsplit

    from openbb_core.app.model.abstract.error import OpenBBError

    parsed = urlsplit(url.strip())

    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in DOCUMENT_HOSTS:
        raise OpenBBError(
            ValueError(
                "Invalid URL supplied, host must be one of "
                + ", ".join(DOCUMENT_HOSTS)
                + " over https."
            )
        )


async def _download(url: str) -> bytes | None:
    """Read one document, or nothing when the host will not serve it."""
    from openbb_tmx.utils.cache import amake_request

    try:
        body = await amake_request(
            url, use_cache=False, accept_type="binary", referer=url
        )
    except Exception:  # noqa: BLE001
        return None

    return body if isinstance(body, bytes) and body.startswith(PDF_MAGIC) else None


async def as_viewer_files(selections: "list[tuple[str, str]]") -> list[dict]:
    """Serve each selected document to the file viewer.

    Parameters
    ----------
    selections : list[tuple[str, str]]
        The URL and the file name of each selected document.

    Returns
    -------
    list[dict]
        One entry per document, carrying the document itself where the host
        served it and the URL to load where it did not.
    """
    import asyncio
    from base64 import b64encode

    for url, _ in selections:
        _check_url(url)

    documents = await asyncio.gather(*(_download(url) for url, _ in selections))
    results: list[dict] = []

    for (url, filename), document in zip(selections, documents):
        entry: dict = {"data_format": {"data_type": "pdf", "filename": filename}}

        if document is None:
            entry["url"] = url
        else:
            entry["content"] = b64encode(document).decode("utf-8")

        results.append(entry)

    return results
