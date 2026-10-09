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


if __name__ == "__main__":
    unittest.main()
