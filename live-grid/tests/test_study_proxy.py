# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json
import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("OPENBB_API_AUTH", "true")
    monkeypatch.setenv("OPENBB_API_USERNAME", "test")
    monkeypatch.setenv("OPENBB_API_PASSWORD", "secret")
    monkeypatch.setenv("LIVE_GRID_STUDY_ORIGIN", "http://arts.test")


def proxy_client(handler):
    from app.study_proxy import attach_study_proxy

    app = FastAPI()
    proxy = attach_study_proxy(app, transport=httpx.MockTransport(handler))
    return TestClient(app), proxy


def test_proxy_admission_and_server_owned_credentials(configured):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"schema_version": 1, "studies": []})

    client, proxy = proxy_client(upstream)
    assert proxy.configured
    assert client.get("/study_catalog").status_code == 401
    response = client.get("/study_catalog", auth=("test", "secret"))
    assert response.json() == {"schema_version": 1, "studies": []}
    assert calls[0].url == httpx.URL("http://arts.test/study_catalog")
    assert calls[0].headers["authorization"] == "Basic dGVzdDpzZWNyZXQ="
    assert (
        client.get("/study_catalog?upstream=http://evil.test", auth=("test", "secret")).status_code
        == 400
    )
    body = {"schema_version": 1, "symbols": ["AAPL"], "columns": []}
    assert client.post("/study_results", json=body, auth=("test", "secret")).status_code == 200
    assert json.loads(calls[-1].content) == body


def test_proxy_request_response_bounds_and_safe_failure(configured):
    client, _ = proxy_client(
        lambda request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
    )
    assert client.get("/study_catalog", auth=("test", "secret")).status_code == 502
    assert (
        client.post(
            "/study_results",
            content=b"x" * 65537,
            headers={"content-type": "application/json"},
            auth=("test", "secret"),
        ).status_code
        == 413
    )
    assert client.post("/study_results", content="{}", auth=("test", "secret")).status_code == 415
    assert (
        client.post(
            "/study_results",
            content="{",
            headers={"content-type": "application/json"},
            auth=("test", "secret"),
        ).status_code
        == 400
    )
    client, _ = proxy_client(
        lambda request: httpx.Response(302, headers={"location": "http://evil.test"})
    )
    response = client.get("/study_catalog", auth=("test", "secret"))
    assert response.status_code == 502 and "evil" not in response.text

    def timeout(request):
        raise httpx.ReadTimeout("private credential details")

    client, _ = proxy_client(timeout)
    response = client.get("/study_catalog", auth=("test", "secret"))
    assert response.status_code == 504 and "private" not in response.text


def test_proxy_disabled_unless_configured_and_secured(configured, monkeypatch):
    for origin, auth in [
        ("", True),
        ("http://user:password@arts.test", True),
        ("http://arts.test/path", True),
        ("http://arts.test", False),
    ]:
        monkeypatch.setenv("LIVE_GRID_STUDY_ORIGIN", origin)
        monkeypatch.setenv("OPENBB_API_AUTH", "true" if auth else "false")
        client, proxy = proxy_client(
            lambda request: pytest.fail("disabled proxy made upstream call")
        )
        assert not proxy.configured
        assert client.get("/study_catalog", auth=("test", "secret")).status_code == 503


def test_live_grid_capability_only_when_proxy_configured(configured, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    app = create_app(api_key="synthetic")
    widgets = TestClient(app).get("/widgets.json", auth=("test", "secret")).json()
    assert widgets["live_grid"]["extra_metadata"]["study_columns_v1"] is True
    monkeypatch.delenv("LIVE_GRID_STUDY_ORIGIN")
    widgets = (
        TestClient(create_app(api_key="synthetic"))
        .get("/widgets.json", auth=("test", "secret"))
        .json()
    )
    assert not widgets["live_grid"].get("extra_metadata", {}).get("study_columns_v1")


def test_proxy_admission_slot_covers_entire_request_and_releases_errors(configured):
    client, proxy = proxy_client(
        lambda request: httpx.Response(200, json={"schema_version": 1, "studies": []})
    )
    assert client.get("/study_catalog", auth=("test", "secret")).status_code == 200
    assert proxy.active == 0
    assert client.post("/study_results", content="bad", auth=("test", "secret")).status_code == 415
    assert proxy.active == 0
    proxy.active = 8
    assert client.get("/study_catalog", auth=("test", "secret")).status_code == 429
    assert proxy.active == 8
