# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""v3/openbq_settings.py: key-mode dashboard and app routes.

pytest with starlette and httpx; openbb_core is stubbed, so any such Python works:
    ~/Developer/OpenBB/.venv/bin/python -m pytest v3/tests -q
"""
import base64
import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DASH = "aaaaaaaa-0000-4000-8000-000000000002"
OTHER = "aaaaaaaa-0000-4000-8000-000000000009"
APP = "aaaaaaaa-0000-4000-8000-000000000003"


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


AUTH = basic("alice", "PLACEHOLDER")


def dash(name="Example", **extra):
    return {"index": DASH, "isFolder": False, "data": {"name": name, "widgets": [], "gridLayout": {}}, **extra}


@pytest.fixture
def env():
    class Env:
        API_AUTH = True
        API_USERNAME = "alice"
        API_PASSWORD = "PLACEHOLDER"
    return Env


@pytest.fixture
def api(tmp_path, monkeypatch, env):
    core = types.ModuleType("openbb_core.env")
    core.Env = env
    cors = types.SimpleNamespace(allow_origins=["*"])
    service = types.ModuleType("openbb_core.app.service.system_service")
    service.SystemService = lambda: types.SimpleNamespace(
        system_settings=types.SimpleNamespace(api_settings=types.SimpleNamespace(cors=cors)))
    monkeypatch.setitem(sys.modules, "openbb_core.env", core)
    monkeypatch.setitem(sys.modules, "openbb_core.app.service.system_service", service)
    monkeypatch.setenv("OPENBQ_SETTINGS_DIR", str(tmp_path))
    module = importlib.reload(importlib.import_module("openbq_settings"))
    app = Starlette(routes=[Route("/{path:path}", lambda request: PlainTextResponse("not here", 404),
                                  methods=["GET", "POST", "PUT", "DELETE"])])
    app.add_middleware(BaseHTTPMiddleware, dispatch=module.middleware)
    return TestClient(app), module


def owned(client, auth=AUTH):
    return client.get("/pro/dash/sync/owned", headers=auth).json()


def post(client, items, auth=AUTH):
    return client.post("/pro/dash/sync", json={"items": items}, headers=auth)


DASH_ROUTES = [("GET", "/pro/dash/sync/owned"), ("GET", "/pro/dash/sync/shared"), ("POST", "/pro/dash/sync")]


@pytest.mark.parametrize("method,path", DASH_ROUTES)
def test_dashboard_routes_answer_404_with_api_auth_off(api, env, method, path):
    client, _ = api
    env.API_AUTH = False
    assert client.request(method, path, headers=AUTH).status_code == 404


@pytest.mark.parametrize("method,path", DASH_ROUTES)
def test_dashboard_routes_refuse_a_missing_or_wrong_credential(api, method, path):
    client, _ = api
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers=basic("alice", "wrong")).status_code == 401


def test_owned_starts_empty_and_shared_is_always_empty(api):
    client, _ = api
    assert owned(client) == {"owned": {}}
    assert client.get("/pro/dash/sync/shared", headers=AUTH).json() == {"shared": {}, "entity_shared": {}}


def test_first_write_stores_the_item_with_server_dates_and_creates_the_root(api, monkeypatch):
    client, module = api
    monkeypatch.setattr(module, "_now", lambda: "2026-10-11T00:00:01Z")
    assert post(client, {DASH: dash()}).json() == {"success": True}
    items = owned(client)["owned"]
    record = items[DASH]
    assert record["updated_date"] == "2026-10-11T00:00:01Z"
    assert (record["created_by"], record["creator"], record["is_shared"]) == ("alice", True, False)
    assert record["content"]["data"] == dash()["data"]
    root_key, root = next((k, v) for k, v in items.items() if v["content"].get("isRoot"))
    assert root["content"]["children"] == [DASH]
    assert record["content"]["parentId"] == root["content"]["index"] == root_key


def test_the_root_lists_a_child_by_its_store_key_not_its_own_index_text(api):
    client, _ = api
    hexed = DASH.replace("-", "")
    post(client, {DASH: dash(index=hexed)})
    items = owned(client)["owned"]
    root = next(v for v in items.values() if v["content"].get("isRoot"))
    assert root["content"]["children"] == [DASH]


def test_a_later_write_keeps_created_date_moves_updated_date_and_keeps_one_root(api, monkeypatch):
    client, module = api
    clock = iter(["2026-10-11T00:00:01Z", "2026-10-11T00:00:02Z"])
    monkeypatch.setattr(module, "_now", lambda: next(clock))
    post(client, {DASH: dash()})
    post(client, {DASH: dash("Renamed")})
    items = owned(client)["owned"]
    assert (items[DASH]["created_date"], items[DASH]["updated_date"]) == ("2026-10-11T00:00:01Z", "2026-10-11T00:00:02Z")
    assert items[DASH]["content"]["data"]["name"] == "Renamed"
    assert sum(1 for v in items.values() if v["content"].get("isRoot")) == 1


def test_delete_removes_one_item_and_leaves_the_rest(api):
    client, _ = api
    post(client, {DASH: dash(), OTHER: dict(dash("Other"), index=OTHER)})
    post(client, {DASH: "DELETE"})
    items = owned(client)["owned"]
    assert DASH not in items and OTHER in items


def test_a_hex_key_is_stored_under_the_dashed_uuid(api):
    client, _ = api
    post(client, {DASH.replace("-", ""): dash()})
    assert DASH in owned(client)["owned"]


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"items": []}', b'{"items": {"%s": 3}}' % DASH.encode(),
                                  b'{"items": {"not-a-uuid": {}}}'])
def test_a_malformed_body_answers_400_and_writes_nothing(api, body):
    client, _ = api
    post(client, {DASH: dash()})
    before = owned(client)
    assert client.post("/pro/dash/sync", content=body, headers=AUTH).status_code == 400
    assert owned(client) == before


def test_a_body_over_5_mb_answers_413_and_writes_nothing(api):
    client, _ = api
    assert post(client, {DASH: dash(blob="x" * 5_000_001)}).status_code == 413
    assert owned(client) == {"owned": {}}


def test_each_credential_has_its_own_store(api, env):
    client, _ = api
    post(client, {DASH: dash()})
    env.API_PASSWORD = "rotated"
    assert owned(client, basic("alice", "rotated")) == {"owned": {}}


def test_a_failed_write_leaves_the_stored_file_intact(api, monkeypatch, tmp_path):
    client, module = api
    post(client, {DASH: dash("Before")})

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(module.os, "replace", broken)
    with pytest.raises(OSError):
        post(client, {DASH: dash("After")})
    [stored] = tmp_path.glob("*.dashboards.json")
    assert json.loads(stored.read_text())[DASH]["content"]["data"]["name"] == "Before"


APP_ROUTES = [("GET", "/pro/user-apps/sync"), ("POST", f"/pro/user-apps/{APP}"), ("DELETE", f"/pro/user-apps/{APP}")]


def app_content(name="Example app"):
    return {"name": name, "widgets": [], "groups": [], "gridLayout": {}, "prompts": []}


@pytest.mark.parametrize("method,path", APP_ROUTES)
def test_app_routes_answer_404_with_api_auth_off(api, env, method, path):
    client, _ = api
    env.API_AUTH = False
    assert client.request(method, path, headers=AUTH).status_code == 404


@pytest.mark.parametrize("method,path", APP_ROUTES)
def test_app_routes_refuse_a_missing_credential(api, method, path):
    client, _ = api
    assert client.request(method, path).status_code == 401


def test_an_app_upserts_lists_in_workspace_shape_and_deletes(api, monkeypatch):
    client, module = api
    clock = iter(["2026-10-11T00:00:01Z", "2026-10-11T00:00:02Z"])
    monkeypatch.setattr(module, "_now", lambda: next(clock))
    assert client.get("/pro/user-apps/sync", headers=AUTH).json() == {"owned": {}, "shared": {}}
    assert client.post(f"/pro/user-apps/{APP}", json=app_content(), headers=AUTH).status_code == 200
    assert client.post(f"/pro/user-apps/{APP}", json=app_content("Renamed"), headers=AUTH).status_code == 200
    record = client.get("/pro/user-apps/sync", headers=AUTH).json()["owned"][APP]
    assert record == {"content": app_content("Renamed"), "creator": True, "is_shared": False,
                      "createdDate": "2026-10-11T00:00:01Z", "updatedDate": "2026-10-11T00:00:02Z",
                      "createdBy": "alice", "sharedWith": []}
    assert client.delete(f"/pro/user-apps/{APP}", headers=AUTH).status_code == 200
    assert client.delete(f"/pro/user-apps/{APP}", headers=AUTH).status_code == 404
    assert client.get("/pro/user-apps/sync", headers=AUTH).json()["owned"] == {}


@pytest.mark.parametrize("path,body,status", [(f"/pro/user-apps/{APP}", b"[]", 400), ("/pro/user-apps/not-a-uuid", b"{}", 400),
                                              (f"/pro/user-apps/{APP}", b'{"name": "%s"}' % (b"x" * 5_000_001), 413)])
def test_a_refused_app_write_stores_nothing(api, path, body, status):
    client, _ = api
    assert client.post(path, content=body, headers=AUTH).status_code == status
    assert client.get("/pro/user-apps/sync", headers=AUTH).json()["owned"] == {}


def test_settings_routes_still_work(api):
    client, _ = api
    assert client.post("/pro/display-settings", json={"theme": "dark"}, headers=AUTH).status_code == 200
    assert client.get("/pro/user", headers=AUTH).json() == {"pro_display_settings": {"theme": "dark"}}


DOCKS = "/pro/dash/sync/system/docks"
SYSTEM_ROUTES = [("GET", DOCKS), ("PUT", DOCKS), ("DELETE", DOCKS)]


def docks(revision, name="Locked widgets"):
    return {"revision": revision, "content": {"id": "docks", "name": name, "hidden": True, "tabs": []}}


def put_docks(client, body, auth=AUTH):
    return client.put(DOCKS, json=body, headers=auth)


@pytest.mark.parametrize("method,path", SYSTEM_ROUTES)
def test_system_routes_answer_404_with_api_auth_off(api, env, method, path):
    client, _ = api
    env.API_AUTH = False
    assert client.request(method, path, headers=AUTH).status_code == 404


@pytest.mark.parametrize("method,path", SYSTEM_ROUTES)
def test_system_routes_refuse_a_missing_or_wrong_credential(api, method, path):
    client, _ = api
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers=basic("alice", "wrong")).status_code == 401


def test_the_docks_starts_absent(api):
    client, _ = api
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": None}


def test_the_docks_round_trips_hidden_and_is_never_listed(api, monkeypatch):
    client, module = api
    monkeypatch.setattr(module, "_now", lambda: "2026-10-11T00:00:01Z")
    put = put_docks(client, docks(5))
    assert put.status_code == 200
    expected = {"id": "docks", "hidden": True, "revision": 5, "creator": True, "content": docks(5)["content"],
                "created_date": "2026-10-11T00:00:01Z", "updated_date": "2026-10-11T00:00:01Z",
                "created_by": "alice", "is_shared": False}
    assert put.json() == {"success": True, "dashboard": expected}
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": expected}
    assert owned(client) == {"owned": {}}


def test_the_docks_is_not_adopted_by_the_root_and_the_list_stays_workspace_shaped(api):
    client, _ = api
    put_docks(client, docks(1))
    post(client, {DASH: dash()})
    items = owned(client)["owned"]
    assert "docks" not in items and DASH in items
    root = next(v for v in items.values() if v["content"].get("isRoot"))
    assert root["content"]["children"] == [DASH]
    assert "parentId" not in client.get(DOCKS, headers=AUTH).json()["dashboard"]["content"]


def test_the_newest_revision_wins(api, monkeypatch):
    client, module = api
    clock = iter(["2026-10-11T00:00:01Z", "2026-10-11T00:00:02Z", "2026-10-11T00:00:03Z"])
    monkeypatch.setattr(module, "_now", lambda: next(clock))
    put_docks(client, docks(10, "first"))
    stale = put_docks(client, docks(9, "stale"))
    assert stale.status_code == 409
    assert stale.json()["dashboard"]["content"]["name"] == "first"
    assert put_docks(client, docks(10, "same revision")).status_code == 200
    newer = put_docks(client, docks(11, "newer")).json()["dashboard"]
    assert (newer["revision"], newer["content"]["name"]) == (11, "newer")
    assert (newer["created_date"], newer["updated_date"]) == ("2026-10-11T00:00:01Z", "2026-10-11T00:00:03Z")


def test_one_docks_per_credential(api, env):
    client, _ = api
    put_docks(client, docks(3))
    env.API_PASSWORD = "rotated"
    assert client.get(DOCKS, headers=basic("alice", "rotated")).json() == {"dashboard": None}


def test_delete_removes_the_docks_and_leaves_the_dashboards(api):
    client, _ = api
    post(client, {DASH: dash()})
    put_docks(client, docks(3))
    assert client.delete(DOCKS + "?revision=3", headers=AUTH).json() == {"success": True}
    assert client.delete(DOCKS + "?revision=0", headers=AUTH).json() == {"success": True}
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": None}
    assert DASH in owned(client)["owned"]
    assert put_docks(client, docks(1)).status_code == 200


def test_the_dashboard_sync_post_cannot_reach_the_docks(api):
    client, _ = api
    put_docks(client, docks(3))
    assert post(client, {"docks": dash()}).status_code == 400
    assert post(client, {"docks": "DELETE"}).status_code == 400
    assert client.get(DOCKS, headers=AUTH).json()["dashboard"]["revision"] == 3


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"content": {}}', b'{"revision": 1}',
                                  b'{"revision": -1, "content": {}}', b'{"revision": 1.5, "content": {}}',
                                  b'{"revision": true, "content": {}}', b'{"revision": "1", "content": {}}',
                                  b'{"revision": 1, "content": []}', b'{"revision": 1, "content": {}, "extra": 1}'])
def test_a_malformed_docks_body_answers_400_and_writes_nothing(api, body):
    client, _ = api
    assert client.put(DOCKS, content=body, headers=AUTH).status_code == 400
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": None}


def test_a_docks_body_over_5_mb_answers_413(api):
    client, _ = api
    body = docks(1)
    body["content"]["blob"] = "x" * 5_000_001
    assert put_docks(client, body).status_code == 413
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": None}


@pytest.mark.parametrize("path", ["/pro/dash/sync/system/other", "/pro/dash/sync/system/", "/pro/dash/sync/system/docks/x"])
def test_an_unreserved_system_id_answers_404(api, path):
    client, _ = api
    assert client.put(path, json=docks(1), headers=AUTH).status_code == 404
    assert client.get(path, headers=AUTH).status_code == 404


def test_post_on_the_docks_is_not_allowed(api):
    client, _ = api
    assert client.post(DOCKS, json=docks(1), headers=AUTH).status_code == 405


def test_a_delete_older_than_the_stored_docks_answers_409_and_keeps_it(api):
    client, _ = api
    put_docks(client, docks(10, "kept"))
    stale = client.delete(DOCKS + "?revision=9", headers=AUTH)
    assert stale.status_code == 409
    assert stale.json()["dashboard"]["content"]["name"] == "kept"
    assert client.get(DOCKS, headers=AUTH).json()["dashboard"]["revision"] == 10
    assert client.delete(DOCKS + "?revision=11", headers=AUTH).json() == {"success": True}
    assert client.get(DOCKS, headers=AUTH).json() == {"dashboard": None}


@pytest.mark.parametrize("query", ["", "?revision=", "?revision=-1", "?revision=1.5", "?revision=x",
                                   "?revision=1&revision=2", "?revision=1&extra=1", "?revision=%EF%BC%91"])
def test_a_delete_without_one_integer_revision_answers_400_and_keeps_the_docks(api, query):
    client, _ = api
    put_docks(client, docks(3))
    assert client.delete(DOCKS + query, headers=AUTH).status_code == 400
    assert client.get(DOCKS, headers=AUTH).json()["dashboard"]["revision"] == 3
