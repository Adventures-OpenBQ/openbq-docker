# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""The Video Library route through the real OpenBB app: the body bdobb's YouTube
card reads, and the widget openbb-platform-api builds from the command.

The app loads every installed openbb_core_extension, this one included (the
editable install registers its entry point). No lifespan runs: TestClient is
not used as a context manager. Basic auth is off because OPENBB_API_AUTH is
unset in the test container."""
from fastapi.testclient import TestClient
from openbb_core.api.rest_api import app
from openbb_platform_api.utils.widgets import build_json

ROUTE = "/api/v1/videos/video"
WORKSPACE = "https://www.youtube.com/watch?v=uYyhswnZkSw"
ODP = "https://www.youtube.com/watch?v=MSlhOFxEdxg"
client = TestClient(app)


def _widget():
    widgets = build_json(app.openapi(), [])
    return next(w for w in widgets.values() if w["endpoint"] == ROUTE)


def test_body_is_the_bare_watch_url_not_an_obbject():
    # The whole point: an OBBject would wrap the url in {"results": ...} and
    # bdobb's YouTubeRenderer needs the string itself.
    r = client.get(ROUTE, params={"video_name": "OpenBB Workspace Demo"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text == WORKSPACE


def test_second_video():
    assert client.get(ROUTE, params={"video_name": "Open Data Platform Demo"}).text == ODP


def test_default_is_the_workspace_demo():
    assert client.get(ROUTE).text == WORKSPACE


def test_unknown_name_is_an_empty_body_as_in_the_reference():
    r = client.get(ROUTE, params={"video_name": "nope"})
    assert r.status_code == 200
    assert r.text == ""


def test_widget_is_a_youtube_card_named_video_library_with_both_options():
    w = _widget()
    assert w["type"] == "youtube"
    assert w["name"] == "Video Library"
    (param,) = [p for p in w["params"] if p["paramName"] == "video_name"]
    assert param["value"] == "OpenBB Workspace Demo"
    assert [o["value"] for o in param["options"]] == [
        "OpenBB Workspace Demo",
        "Open Data Platform Demo",
    ]
