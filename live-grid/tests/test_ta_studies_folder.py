# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Folder studies and time parameters on the simple chart (spec 2026-11-04 §1, §2, §3)."""
import os
import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import openbq_ta
from app.main import create_app
from openbq_ta import studies

MID = '''
import polars as pl
from openbq_ta.studies import study

@study(name="mid_line", label="Mid {label}", params={"period": 5, "mult": 1.0},
       colors={"mid": "#fff"}, pane="price", windows=("period",))
def mid(p):
    return [(((pl.col("high") + pl.col("low")) / 2).rolling_mean(p["period"]) * p["mult"])
            .alias("mid")]
'''


async def daily_bars(symbol, interval, start, end, *args, **kwargs):
    rows, day = [], date(2025, 1, 1)
    while len(rows) < 300:
        if day.weekday() < 5:
            o = day.toordinal() % 97 + 100.0
            rows.append({"date": f"{day.isoformat()}T00:00:00", "open": o, "high": o + 2,
                         "low": o - 2, "close": o + 1, "adjusted_close": o + 1, "volume": 1000.0})
        day += timedelta(days=1)
    return rows, {}


@pytest.fixture
def chart(tmp_path, monkeypatch):
    monkeypatch.setenv("TA_STUDIES_DIR", str(tmp_path))
    monkeypatch.setattr("app.main.build_series", daily_bars)
    yield TestClient(create_app(api_key="test-key")), tmp_path
    for stem in list(studies.installed()):
        studies.unload(stem)
    studies._MTIMES.clear()


def traces(answer):
    assert answer.status_code == 200, answer.text
    # legend names carry the parameters, `Mid a(5,1)`; key by the bare label
    return {re.sub(r"\(.*\)$", "", t["name"]): t for t in answer.json()["data"]}


def test_a_folder_study_is_drawn_on_the_simple_chart(chart):
    api, folder = chart
    (folder / "mid.py").write_text(MID.replace("{label}", "a"))
    drawn = traces(api.get("/ta_chart", params={"indicators": "mid_line"}))
    assert any(y is not None for y in drawn["Mid a"]["y"])


def test_a_changed_file_is_picked_up_at_the_next_request(chart):
    api, folder = chart
    path = folder / "mid.py"
    path.write_text(MID.replace("{label}", "a"))
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert "Mid a" in traces(api.get("/ta_chart", params={"indicators": "mid_line"}))
    path.write_text(MID.replace("{label}", "b"))
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    assert "Mid b" in traces(api.get("/ta_chart", params={"indicators": "mid_line"}))


def test_a_broken_folder_file_does_not_break_the_chart(chart):
    api, folder = chart
    (folder / "mid.py").write_text(MID.replace("{label}", "a"))
    (folder / "broken.py").write_text("this is not python")
    assert "Mid a" in traces(api.get("/ta_chart", params={"indicators": "mid_line,rsi"}))


def test_a_folder_studys_float_parameter_is_typed_by_its_default(chart):
    api, folder = chart
    (folder / "mid.py").write_text(MID.replace("{label}", "a"))
    plain = traces(api.get("/ta_chart", params={"indicators": "mid_line:period=7"}))["Mid a"]["y"]
    doubled = traces(api.get("/ta_chart", params={"indicators": "mid_line:period=7:mult=2.5"}))
    assert doubled["Mid a"]["y"][-1] == pytest.approx(plain[-1] * 2.5)


def test_ta_chart_with_an_obs_anchor_and_no_tape_draws_the_rest(chart):
    api, _ = chart
    answer = api.get("/ta_chart", params={"indicators": "rsi", "anchor": "OBS-3"})
    drawn = traces(answer)
    assert "RSI" in drawn and "Anchored VWAP" not in drawn
    assert "avwap" in answer.json()["layout"]["title"]["text"]


def test_an_expression_anchor_is_dropped_with_a_note_not_a_502(chart):
    api, _ = chart
    answer = api.get("/ta_chart", params={"indicators": "rsi", "anchor": "T-1bd@open"})
    assert "host resolves" in answer.json()["layout"]["title"]["text"]


def test_health_reports_the_engine_version(chart):
    api, _ = chart
    assert api.get("/health").json()["openbq_ta"] == openbq_ta.__version__


def test_a_study_dropped_between_pushes_sends_a_full_figure(chart, monkeypatch):
    api, _ = chart
    from datetime import datetime
    tape = [datetime(2025, 1, 10, 12, i) for i in (3, 2, 1)]
    seen = iter([tape, []])

    async def fake(symbol, indicators, recorder):
        return list(next(seen, []))

    monkeypatch.setattr("app.main._trades", fake)
    monkeypatch.setenv("TA_PUSH_INTERVAL_MS", "0")
    with api.websocket_connect("/ta_chart_ws?symbol=AAPL&indicators=rsi&anchor=OBS-3") as ws:
        first, second = ws.receive_json(), ws.receive_json()
    assert first["type"] == "figure"
    assert any(t["name"].startswith("Anchored VWAP") for t in first["figure"]["data"])
    assert second["type"] == "figure", "a changed trace layout must not arrive as a delta"
    assert not any(t["name"].startswith("Anchored VWAP") for t in second["figure"]["data"])


def test_an_obs_anchor_on_the_eodhd_source_is_resolved_not_a_502(chart, monkeypatch):
    from datetime import datetime
    api, _ = chart

    async def tape(symbol, indicators, recorder):
        return [datetime(2025, 1, 10, 12, i) for i in (3, 2, 1)]

    monkeypatch.setattr("app.main._trades", tape)
    answer = api.get("/ta_chart", params={"source": "eodhd", "anchor": "OBS-3"})
    assert any(t["name"].startswith("Anchored VWAP") for t in traces_raw(answer))


def traces_raw(answer):
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]
