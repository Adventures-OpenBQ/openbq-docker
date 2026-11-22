# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""A file viewer must not publish an upstream error page as a PDF."""
import base64
import unittest
from unittest.mock import patch


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise ValueError(f"Upstream HTTP {self.status}")

    async def read(self):
        return self.body


class NasdaqPdf(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from openbb_nasdaq.utils import helpers
        self.helpers = helpers
        helpers.download_filing_pdf.cache_clear()
        self.url = "https://app.quotemedia.com/data/downloadFiling?symbol=AAPL"

    async def document(self, body, status=200):
        self.headers = None

        async def request(url, **kwargs):
            self.assertEqual(url, self.url)
            self.headers = kwargs["headers"]
            return await kwargs["response_callback"](Response(body, status), None)

        with patch("openbb_core.provider.utils.helpers.amake_request", side_effect=request):
            return await self.helpers.open_filing_document(self.url)

    async def test_html_error_page_is_not_advertised_as_a_pdf(self):
        result = await self.document(b"<!DOCTYPE html><title>Cloudflare blocked</title>")
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)
        self.assertNotIn("Cloudflare blocked", result["content"])

    async def test_http_error_is_refused_even_with_a_pdf_shaped_body(self):
        result = await self.document(b"%PDF-1.4\n%%EOF", 403)
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)

    async def test_truncated_pdf_is_not_published(self):
        result = await self.document(b"%PDF-1.4\ntruncated response")
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)

    async def test_pdf_bytes_round_trip_with_the_pdf_accept_header(self):
        body = b"%PDF-1.4\nPDF transport fixture\n%%EOF\n"
        result = await self.document(body)
        self.assertEqual(base64.b64decode(result["content"], validate=True), body)
        self.assertEqual(result["data_format"]["data_type"], "pdf")
        self.assertTrue(self.headers["Accept"].startswith("application/pdf"))


if __name__ == "__main__":
    unittest.main()
