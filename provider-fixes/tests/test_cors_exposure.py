# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The installed API must make daily-price transport declarations visible to Fetch."""
import unittest

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from openbb_platform_api.app.bootstrap import apply_cors_from_system_service

ORIGIN = "https://browser.example"
EXPOSED = {"link", "content-range", "access-control-expose-headers"}


class CorsExposureTest(unittest.TestCase):
    def assert_daily_price_exposure(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        exposed = response.headers.get("access-control-expose-headers", "")
        self.assertEqual({name.strip().lower() for name in exposed.split(",") if name.strip()}, EXPOSED)

    def test_default_api_exposes_its_transport_policy(self):
        from openbb_core.api.rest_api import app

        response = TestClient(app).get("/openapi.json", headers={"Origin": ORIGIN})
        self.assert_daily_price_exposure(response)

    def test_bootstrap_exposes_continuation_and_range_on_200(self):
        app = FastAPI()

        @app.get("/prices")
        def prices():
            return JSONResponse({"results": []}, headers={
                "Link": '</prices?page=2>; rel="next"',
                "Content-Range": "items 0-57/100",
            })

        self.assertTrue(apply_cors_from_system_service(app))
        self.assertFalse(apply_cors_from_system_service(app))
        response = TestClient(app).get("/prices", headers={"Origin": ORIGIN})
        self.assert_daily_price_exposure(response)
        self.assertEqual(response.headers["link"], '</prices?page=2>; rel="next"')
        self.assertEqual(response.headers["content-range"], "items 0-57/100")
        self.assertEqual(response.json(), {"results": []})

    def test_bootstrap_preserves_existing_custom_cors(self):
        app = FastAPI()
        app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=["GET"],
                           allow_credentials=True, expose_headers=["X-Custom"])

        self.assertFalse(apply_cors_from_system_service(app))
        response = TestClient(app).get("/openapi.json", headers={"Origin": ORIGIN})
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(response.headers["access-control-expose-headers"], "X-Custom")
