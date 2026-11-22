# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Offline checks for the USDA weather bulletin PDF download boundary."""
import base64
import unittest
from unittest.mock import AsyncMock, patch


PDF = b"%PDF-1.4\nUSDA weather transport fixture\n%%EOF\n"
URL = "https://esmis.nal.usda.gov/weather/bulletin.pdf"


class Response:
    def __init__(self, body, status):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self):
        return self.body


class Session:
    def __init__(self, body, status):
        self.response = Response(body, status)
        self.options = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        if url != URL:
            raise AssertionError(f"Unexpected transport destination: {url}")
        self.options = kwargs
        return self.response


class UsdaDocumentSafety(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from openbb_government_us.usda.models.weather_bulletin_download import (
            UsdaWeatherBulletinDownloadFetcher,
        )
        self.fetcher = UsdaWeatherBulletinDownloadFetcher

    async def extract(self, body=PDF, status=200):
        self.session = Session(body, status)
        query = self.fetcher.transform_query({"urls": URL})
        with patch(
            "openbb_core.provider.utils.helpers.get_async_requests_session",
            new=AsyncMock(return_value=self.session),
        ):
            data = await self.fetcher.aextract_data(query, None)
        return self.fetcher.transform_data(query, data)

    async def test_html_and_incomplete_pdf_bodies_are_rejected(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        for body in (b"<html>Source denial marker</html>", b"%PDF-1.4\ntruncated", b"%PDF-1.4\n%%EOF" + b"x" * 2048, b"prefix\n" + PDF):
            with self.subTest(body=body[:30]):
                with self.assertRaises(OpenBBError) as error:
                    await self.extract(body)
                self.assertNotIn("Source denial marker", str(error.exception))

    async def test_non_success_status_is_rejected_even_with_pdf_bytes(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        for status in (302, 403, 500):
            with self.subTest(status=status), self.assertRaises(OpenBBError):
                await self.extract(PDF, status)

    async def test_successful_pdf_round_trips_without_following_redirects(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        for status, body in ((200, PDF), (206, PDF), (200, PDF + b" " * 2042)):
            with self.subTest(status=status):
                try:
                    result = (await self.extract(body, status))[0]
                except OpenBBError as error:
                    self.fail(f"Successful HTTP {status} PDF was refused: {error}")
                self.assertEqual(base64.b64decode(result.content, validate=True), body)
                self.assertEqual(result.data_format, {"data_type": "pdf", "filename": "bulletin.pdf"})
                self.assertIs(self.session.options.get("allow_redirects"), False)

    async def test_existing_origin_and_pdf_suffix_restrictions_precede_transport(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        for url in (
            "http://127.0.0.1/private.pdf?esmis.nal.usda.gov",
            "http://esmis.nal.usda.gov/bulletin.pdf",
            "https://esmis.nal.usda.gov.example.com/bulletin.pdf",
            "https://esmis.nal.usda.gov./bulletin.pdf",
            "https://user:password@esmis.nal.usda.gov/bulletin.pdf",
            "https://esmis.nal.usda.gov:443/bulletin.pdf",
            "https://esmis.nal.usda.gov:8443/bulletin.pdf",
            "https://esmis.nal.usda.gov:invalid/bulletin.pdf",
            "https://esmis.nal.usda.gov/bulletin.txt",
        ):
            with self.subTest(url=url), patch(
                "openbb_core.provider.utils.helpers.get_async_requests_session", new=AsyncMock()
            ) as session:
                query = self.fetcher.transform_query({"urls": url})
                with self.assertRaises(OpenBBError):
                    await self.fetcher.aextract_data(query, None)
                session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
