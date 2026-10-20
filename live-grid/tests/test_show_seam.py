# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""/ta_chart?show_seam: where history ends and live begins (Ep 10, example 3)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import seam_case

GOLDEN = Path(__file__).parent / "fixtures" / "ta_chart_no_seam.json"
QUERY = {"symbol": "AAPL", "macro": "classic-momentum", "start": "2026-10-01",
         "end": "2026-10-18"}


def _client(monkeypatch, lake_on=False, meta=None):
    from app.lake import LakeTicks
    from app.main import create_app

    seam_case.patch(monkeypatch, meta)
    monkeypatch.setattr(LakeTicks, "from_env", staticmethod(lambda: object() if lake_on else None))
    return TestClient(create_app(api_key="test-key"))


@pytest.mark.parametrize("extra", [{}, {"show_seam": "false"}])
def test_without_show_seam_the_figure_is_byte_identical_to_before(monkeypatch, extra):
    # GOLDEN was written by /ta_chart before show_seam existed, from the same seam_case bars.
    response = _client(monkeypatch).get("/ta_chart", params={**QUERY, **extra})
    assert response.status_code == 200
    assert response.content == GOLDEN.read_bytes()


def _seam(monkeypatch, **kwargs):
    figure = _client(monkeypatch, **kwargs).get(
        "/ta_chart", params={**QUERY, "show_seam": "true"}).json()
    rects = [(s["label"]["text"], s["x0"], s["x1"]) for s in figure["layout"]["shapes"]
             if s["type"] == "rect"]
    lines = [s["x0"] for s in figure["layout"]["shapes"]
             if s["type"] == "line" and s["xref"] == "x"]
    return figure["layout"]["title"]["text"], rects, lines


def test_show_seam_shades_each_span_and_marks_the_seam(monkeypatch):
    title, rects, lines = _seam(monkeypatch, lake_on=True)
    # Bars 10-12..10-18: provider to the first flushed day, two lake days merged into one
    # span, then kdb from the seam to the last bar.
    assert rects == [
        ("provider", "2026-10-12T00:00:00", "2026-10-15T00:00:00"),
        ("lake", "2026-10-15T00:00:00", "2026-10-17T00:00:00"),
        ("kdb", "2026-10-17T00:00:00", "2026-10-18T00:00:00"),
    ]
    assert lines == ["2026-10-17T00:00:00"]
    assert title.endswith(
        "<br><sup>history 3 · lake 2 days · live 2 · seam 2026-10-17T00:00:00</sup>")


def test_without_lake_read_back_the_subtitle_says_lake_off(monkeypatch):
    meta = {**seam_case.META, "rows_from_lake": 0, "lake_days": []}
    title, rects, _ = _seam(monkeypatch, meta=meta)
    assert "· lake off ·" in title and "lake 0 days" not in title
    assert [r[0] for r in rects] == ["provider", "kdb"]


def test_pure_history_has_no_seam_line(monkeypatch):
    meta = {"rows_from_ticks": 0, "seam": None}
    title, rects, lines = _seam(monkeypatch, meta=meta)
    assert title.endswith("<sup>history 7 · lake off · live 0 · seam none</sup>")
    assert [r[0] for r in rects] == ["provider"] and lines == []


def test_the_widget_offers_show_seam_off_by_default(monkeypatch):
    params = {p["paramName"]: p for p in
              _client(monkeypatch).get("/widgets.json").json()["ta_chart"]["params"]}
    assert params["show_seam"]["label"] == "Show seam"
    assert params["show_seam"]["type"] == "boolean" and params["show_seam"]["value"] is False


def test_the_stream_draws_the_seam_too(monkeypatch):
    """The card streams over /ta_chart_ws; its first figure replaces the REST one."""
    client = _client(monkeypatch, lake_on=True)
    query = "&".join(f"{k}={v}" for k, v in {**QUERY, "show_seam": "true"}.items())
    with client.websocket_connect(f"/ta_chart_ws?{query}") as ws:
        message = ws.receive_json()
    assert message["type"] == "figure"
    assert "lake 2 days · live 2" in message["figure"]["layout"]["title"]["text"]
