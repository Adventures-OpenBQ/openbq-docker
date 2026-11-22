# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Congress file viewers must fetch only their public document sources."""
import base64
import importlib
import unittest
from unittest.mock import patch

FETCHERS = [
    ("bill_text", "CongressBillTextFetcher"),
    ("amendment_text", "CongressAmendmentTextFetcher"),
]
URL = "https://www.govinfo.gov/content/pkg/BILLS-119hr1enr/pdf/BILLS-119hr1enr.pdf"
PDF = b"%PDF-1.4\nDocument transport fixture\n%%EOF\n"

class Response:
    def __init__(self, content, status):
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"Upstream HTTP {self.status_code}")

class CongressDocuments(unittest.IsolatedAsyncioTestCase):
    async def extract(self, module, name, urls, content=PDF, status=200):
        fetcher = getattr(importlib.import_module("openbb_government_us.congress.models." + module), name)
        self.requests = []
        self.options = []
        def request(url, **kwargs):
            self.requests.append(url)
            self.options.append(kwargs)
            return Response(content, status)
        with patch("openbb_core.provider.utils.helpers.make_request", side_effect=request):
            return await fetcher.aextract_data(fetcher.transform_query({"urls": urls}))

    async def test_invalid_origins_never_reach_transport(self):
        urls = [
            "http://127.0.0.1/private.txt?govinfo.gov",
            "https://govinfo.gov.example.com/private.pdf",
            "http://www.govinfo.gov/document.pdf",
            "https://user:password@www.govinfo.gov/document.pdf",
            "https://www.govinfo.gov:8443/document.pdf",
            "https://www.govinfo.gov:invalid/document.pdf",
            "https://www.govinfo.gov./document.pdf",
        ]
        for module, name in FETCHERS:
            for url in urls:
                with self.subTest(module=module, url=url):
                    result = await self.extract(module, name, [url])
                    self.assertEqual(result[0].get("error_type"), "invalid_url")
                    self.assertEqual(self.requests, [])

    async def test_complete_public_pdf_round_trips(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                result = await self.extract(module, name, [URL])
                self.assertEqual(base64.b64decode(result[0]["content"], validate=True), PDF)
                self.assertEqual(result[0]["data_format"]["data_type"], "pdf")
                self.assertIs(self.options[0].get("allow_redirects"), False)

    async def test_text_documents_and_standard_https_port_remain_supported(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                result = await self.extract(module, name, ["https://www.govinfo.gov:443/content/document.txt"], b"Public document text")
                self.assertEqual(result[0]["content"], "Public document text")
                self.assertEqual(result[0]["data_format"]["data_type"], "text")
        result = await self.extract(*FETCHERS[0], ["https://www.congress.gov/document.html"], b"Public bill text")
        self.assertEqual(result[0]["content"], "Public bill text")

    async def test_html_is_not_published_as_pdf(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                result = await self.extract(module, name, [URL], b"<html>Access denied</html>")
                self.assertEqual(result[0].get("error_type"), "download_error")
                self.assertNotIn("data_format", result[0])
                self.assertNotIn("Access denied", result[0]["content"])

    async def test_truncated_pdf_is_not_published(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                result = await self.extract(module, name, [URL], b"%PDF-1.4 incomplete")
                self.assertEqual(result[0].get("error_type"), "download_error")
                self.assertNotIn("data_format", result[0])

    async def test_http_errors_and_redirects_are_not_published_as_pdf(self):
        for module, name in FETCHERS:
            for status in [403, 302]:
                with self.subTest(module=module, status=status):
                    result = await self.extract(module, name, [URL], PDF, status)
                    self.assertEqual(result[0].get("error_type"), "download_error")
                    self.assertNotIn("data_format", result[0])

    async def test_malformed_url_is_a_document_error(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                try:
                    result = await self.extract(module, name, ["https://[govinfo.gov/document.pdf"])
                except ValueError as exc:
                    self.fail(f"Malformed document URL escaped per-file handling: {exc}")
                self.assertEqual(result[0].get("error_type"), "invalid_url")
                self.assertEqual(self.requests, [])

    async def test_empty_and_mixed_selections_preserve_valid_documents(self):
        for module, name in FETCHERS:
            with self.subTest(module=module):
                self.assertEqual(await self.extract(module, name, []), [])
                result = await self.extract(module, name, ["https://invalid.example/document.pdf", URL])
                self.assertEqual(result[0]["error_type"], "invalid_url")
                self.assertEqual(base64.b64decode(result[1]["content"], validate=True), PDF)
                self.assertEqual(self.requests, [URL])

if __name__ == "__main__":
    unittest.main()
