# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Cboe document viewers must distinguish valid files from upstream failures."""
import base64
import unittest
from unittest.mock import patch


class Response:
    def __init__(self, body, status):
        self.body = body
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise ValueError(f"Upstream HTTP {self.status}")

    async def read(self):
        return self.body


class CboePdf(unittest.IsolatedAsyncioTestCase):
    async def document(self, body, status=200):
        from openbb_cboe.utils.helpers import open_index_document

        async def request(url, **kwargs):
            self.assertEqual(url, "https://cdn.cboe.com/a.pdf")
            return await kwargs["response_callback"](Response(body, status), None)

        with patch("openbb_core.provider.utils.helpers.amake_request", side_effect=request):
            return await open_index_document("https://cdn.cboe.com/a.pdf")

    async def test_html_is_not_published_as_pdf(self):
        result = await self.document(b"<!DOCTYPE html><title>Access denied</title>")
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)
        self.assertNotIn("Access denied", result["content"])

    async def test_http_error_is_not_published_even_for_pdf(self):
        result = await self.document(b"%PDF-1.4\n%%EOF\n", 403)
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)

    async def test_truncated_pdf_is_not_published(self):
        result = await self.document(b"%PDF-1.4\ntruncated response")
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)

    async def test_complete_pdf_round_trips(self):
        body = b"%PDF-1.4\nDocument transport fixture\n%%EOF\n"
        result = await self.document(body)
        self.assertEqual(result["data_format"], {"data_type": "pdf", "filename": "a.pdf"})
        self.assertEqual(base64.b64decode(result["content"], validate=True), body)

    async def test_redirect_is_not_published_as_pdf(self):
        result = await self.document(b"%PDF-1.4\n%%EOF\n", 302)
        self.assertEqual(result.get("error_type"), "download_error")
        self.assertNotIn("data_format", result)


if __name__ == "__main__":
    unittest.main()
