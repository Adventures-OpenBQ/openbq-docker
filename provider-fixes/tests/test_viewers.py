# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Federal Reserve file viewers return [] for an empty selection."""
import unittest

# The 17 Fed multi_file_viewer widgets post to these 15 paths (the three NY widgets share one).
ENDPOINTS = [
    "/api/v1/federal_reserve/fomc_documents_download",
    "/api/v1/federal_reserve/ffiec/bhcpr_report_download",
    "/api/v1/federal_reserve/ffiec/financial_report_pdf_download",
] + [
    f"/api/v1/federal_reserve/{slug}/regional_publications_download"
    for slug in ("atlanta", "boston", "chicago", "cleveland", "dallas", "kc",
                 "minneapolis", "ny", "philadelphia", "richmond", "sf", "stl")
]


class FedViewerEmptySelectionTest(unittest.TestCase):
    def test_null_and_empty_url_return_empty_list(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from openbb_federal_reserve.federal_reserve_router import router

        app = FastAPI()
        app.include_router(router.api_router, prefix="/api/v1/federal_reserve")
        client = TestClient(app)
        for endpoint in ENDPOINTS:
            for body in ({"url": None}, {"url": []}):
                with self.subTest(endpoint=endpoint, body=body):
                    response = client.post(endpoint, json=body)
                    self.assertEqual((response.status_code, response.json()), (200, []))


class UsdaWeatherBulletinEmptySelectionTest(unittest.TestCase):
    def test_null_and_missing_urls_return_empty_list(self):
        from fastapi.testclient import TestClient
        from openbb_core.api.rest_api import app

        client = TestClient(app, raise_server_exceptions=False)
        endpoint = "/api/v1/usda/weather_bulletins_download?provider=usda"
        for body in ({"urls": None}, {}):
            with self.subTest(body=body):
                response = client.post(endpoint, json=body)
                self.assertEqual((response.status_code, response.json()), (200, []))

    def test_selected_urls_still_parse(self):
        from openbb_government_us.usda.models.weather_bulletin_download import (
            UsdaWeatherBulletinDownloadFetcher as Fetcher,
        )

        for urls in ("a.pdf,b.pdf", ["a.pdf", "b.pdf"], {"urls": ["a.pdf", "b.pdf"]}):
            with self.subTest(urls=urls):
                self.assertEqual(Fetcher.transform_query({"urls": urls}).urls, ["a.pdf", "b.pdf"])


if __name__ == "__main__":
    unittest.main()
