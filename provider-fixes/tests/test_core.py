# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbb-core overlay: error mapping and required provider inputs."""
import asyncio
import json
import os
import sys
import unittest
from unittest import mock

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from openbb_core.api.app_loader import AppLoader
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.query_params import QueryParams


class ItemQueryParams(QueryParams):
    limit: int
    symbol: str


class BalanceQuery(QueryParams):
    """Named like openbq-yfinance's query models: no "QueryParams" in the title."""

    symbol: str


class ItemData(BaseModel):
    symbol: str


def _app() -> FastAPI:
    """A small app with the overlay's handlers, registered the way openbb-core does."""
    app = FastAPI()
    AppLoader.add_exception_handlers(app)

    @app.get("/timeout")
    async def timeout(message: str = ""):
        raise TimeoutError(message)

    @app.get("/non_json")
    async def non_json():
        json.loads("<html>blocked</html>")

    @app.get("/data")
    async def data():
        return ItemData()

    @app.get("/openbb")
    async def openbb():
        raise OpenBBError("bad input")

    @app.get("/query_params")
    async def query_params(request: Request):
        return ItemQueryParams(**request.query_params)

    @app.get("/balance")
    async def balance(request: Request):
        return BalanceQuery(**request.query_params)

    @app.get("/widgets.json")
    async def widgets():
        return {}

    return app


def _get(app: FastAPI, url: str, **kwargs) -> httpx.Response:
    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get(url, **kwargs)

    return asyncio.run(run())


class ErrorMappingTest(unittest.TestCase):
    app = _app()

    def test_missing_field_is_422(self):
        # A provider QueryParams missing a required field: not in the query string.
        response = _get(self.app, "/query_params?limit=1")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["type"], "missing")

    def test_missing_field_of_any_query_model_is_422(self):
        response = _get(self.app, "/balance")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["type"], "missing")

    def test_query_param_validation_shape_unchanged(self):
        response = _get(self.app, "/query_params?limit=x&symbol=A")
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail[0]["loc"], ["query", "limit"])
        self.assertEqual(detail[0]["type"], "int_parsing")

    def test_timeout_is_504_with_message(self):
        response = _get(self.app, "/timeout?message=EIA%20timed%20out")
        self.assertEqual((response.status_code, response.json()["detail"]), (504, "EIA timed out"))
        response = _get(self.app, "/timeout")
        self.assertEqual(response.status_code, 504)
        self.assertIn("did not respond in time", response.json()["detail"])

    def test_non_json_is_502(self):
        response = _get(self.app, "/non_json")
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json()["detail"],
                         "The data source returned a response that is not valid JSON.")

    def test_missing_data_field_stays_500(self):
        # Upstream dropped a key from a provider Data model: not the client's input.
        response = _get(self.app, "/data")
        self.assertEqual(response.status_code, 500, response.text)

    def test_openbb_error_still_400(self):
        response = _get(self.app, "/openbb")
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "bad input"))


class SharedRouteTest(unittest.TestCase):
    def test_required_for_one_provider_only(self):
        from pydantic.fields import FieldInfo
        from openbb_core.app.provider_interface import ProviderInterface

        def fields(**f):
            return {"QueryParams": {"fields": f}}

        _, extra = ProviderInterface._extract_params({
            "openbb": fields(),
            "a": fields(symbol=FieldInfo(annotation=str)),
            "b": fields(symbol=FieldInfo(annotation=str, default=None)),
        })
        _, annotation, default = extra["symbol"]
        self.assertIsNone(default.default)  # the route stays optional
        self.assertEqual(default.json_schema_extra, {"a": {"x-widget_config": {"optional": False}}})

    def test_required_data_field_gets_no_widget_stamp(self):
        from pydantic.fields import FieldInfo
        from openbb_core.app.provider_interface import ProviderInterface

        _, extra = ProviderInterface._extract_data({
            "openbb": {"Data": {"fields": {}}},
            "a": {"Data": {"fields": {"value": FieldInfo(annotation=float)}}},
        })
        _, _, default = extra["value"]
        self.assertFalse(default.json_schema_extra, default.json_schema_extra)


class InstalledRoutesTest(unittest.TestCase):
    """The real app built from the installed pinned extensions."""

    @classmethod
    def setUpClass(cls):
        from openbb_core.api.rest_api import app

        cls.app = app

    def test_missing_provider_field_is_422(self):
        # cftc's `code` is a provider-only required field; start_date puts a date in the error input.
        response = _get(self.app, "/api/v1/cftc/cot?provider=cftc&start_date=2024-01-02")
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertEqual((detail["type"], detail["loc"]), ("missing", ["code"]))

    def test_timeout_and_non_json_keep_cors_headers(self):
        # rest_api adds CORSMiddleware with the default allow_origins ["*"].
        from openbb_core.app.command_runner import StaticCommandRunner as Runner

        url = "/api/v1/cftc/cot?provider=cftc&code=045601"
        for raised, status in ((TimeoutError("slow"), 504), (json.JSONDecodeError("x", "<html>", 0), 502)):
            with mock.patch.object(Runner, "_command", side_effect=raised):
                response = _get(self.app, url, headers={"Origin": "https://example.com"})
            self.assertEqual(response.status_code, status, response.text)
            self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        response = _get(self.app, "/api/v1/cftc/cot?provider=cftc", headers={"Origin": "https://example.com"})
        self.assertEqual((response.status_code, response.headers.get("access-control-allow-origin")), (422, "*"))

    def test_required_provider_inputs_are_not_optional(self):
        from openbb_core.app.provider_interface import ProviderInterface
        from openbb_core.provider.utils.helpers import to_snake_case
        from openbb_platform_api.utils.widgets import build_json

        openapi = self.app.openapi()
        widgets = build_json(openapi, [])
        pmap = ProviderInterface().map
        required, wrong, api_required, shared = [], [], [], []
        for wid, widget in widgets.items():
            operation = openapi["paths"].get(widget["endpoint"], {}).get("get", {})
            model = operation.get("model")
            params = {p.get("paramName"): p for p in widget.get("params", []) if isinstance(p, dict)}
            provider = params.get("provider", {}).get("value")
            if not wid.endswith("_obb") or provider not in pmap.get(model, {}):
                continue
            api = {p["name"]: p for p in operation.get("parameters", [])}
            standard = pmap[model].get("openbb", {}).get("QueryParams", {}).get("fields", {})
            for name, field in pmap[model][provider]["QueryParams"]["fields"].items():
                param = params.get(to_snake_case(name).replace(".", "_"))
                if name in standard or param is None:
                    continue
                if not field.is_required():
                    # Another provider may require the same input on this route.
                    others = [f for p, m in pmap[model].items() if p != provider
                              for n, f in m["QueryParams"]["fields"].items() if n == name and f.is_required()]
                    if others:
                        shared.append((wid, param["paramName"], param.get("optional")))
                    continue
                required.append((wid, param["paramName"]))
                if param.get("optional") is not False:
                    wrong.append((wid, param["paramName"]))
                if api.get(param["paramName"], {}).get("required"):
                    api_required.append((wid, param["paramName"]))
        print(f"\nrequired provider inputs in _obb widgets: {len(required)}; not optional:false: {len(wrong)}; "
              f"same input optional for another provider on a shared route: {len(shared)}", file=sys.stderr)
        self.assertTrue(required)
        self.assertEqual(wrong, [], f"{len(wrong)} required inputs still optional")
        self.assertEqual(api_required, [])  # the shared route itself stays optional
        self.assertEqual([s for s in shared if s[2] is not True], [])
