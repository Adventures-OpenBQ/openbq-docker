# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The TMX file viewers read only https documents from the hosts TMX serves them from."""
import unittest
from unittest import mock

VIEWERS = ["/api/v1/tmx/equity/filings_view", "/api/v1/tmx/index/document_view"]
ALLOWED = [
    "https://app.quotemedia.com/data/downloadFiling?symbol=AC%3ACA&dateFiled=2026-09-28",
    "https://spindices.com/documents/methodologies/methodology-sp-tsx-canadian-indices.pdf",
    "https://us.spindices.com/documents/methodologies/methodology-sp-shariah-indices.pdf",
    "https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-tsx-60-vix-index.pdf",
]
REFUSED = [
    "http://openbq-mcp:6999/mcp",
    "https://openbq-mcp:6999/mcp",
    "http://app.quotemedia.com/data/downloadFiling",
    "https://app.quotemedia.com.example.com/x.pdf",
    "https://app.quotemedia.com@openbq-mcp:6999/x.pdf",
    "file:///etc/passwd",
    [ALLOWED[0], "http://169.254.169.254/latest/meta-data/"],
]


class TmxViewerHostTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from openbb_core.api.rest_api import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.fetch = mock.AsyncMock(return_value=b"%PDF-1.7")
        for target, value in (
            ("openbb_tmx.utils.cache.amake_request", self.fetch),
            ("openbb_tmx.routers.index._documents", mock.AsyncMock(return_value=[])),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_other_hosts_are_refused_without_a_request(self):
        for endpoint in VIEWERS:
            for url in REFUSED:
                with self.subTest(endpoint=endpoint, url=url):
                    response = self.client.post(endpoint, json={"url": url})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("host must be", response.json()["detail"])
        self.fetch.assert_not_called()

    def test_tmx_document_hosts_are_read(self):
        for endpoint in VIEWERS:
            for url in ALLOWED:
                with self.subTest(endpoint=endpoint, url=url):
                    response = self.client.post(endpoint, json={"url": url})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("content", response.json()[0])

    def test_empty_selection_is_still_empty(self):
        for endpoint in VIEWERS:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, json={"url": []})
                self.assertEqual((response.status_code, response.json()), (200, []))


if __name__ == "__main__":
    unittest.main()
