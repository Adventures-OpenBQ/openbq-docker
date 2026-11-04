# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The bars/SMA widget (spec 2026-11-04 §4; the 0.1 timeseries contract of 2026-10-27 §1, P7)."""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import bars_widget
from app.main import create_app

SCHEMA = json.loads((Path(__file__).parent / "fixtures"
                     / "backend-widget-capabilities-0.1.schema.json").read_text())
TOKEN = re.compile(r"^[1-9][0-9]{0,3}(s|m|h|d|w|M)$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
COLUMNS = {"time", "close", "sma_20", "sma_50", "sma_200"}


async def weekday_bars(symbol, interval, start, end, *args, **kwargs):
    rows, day, last = [], date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    while day <= last:
        if day.weekday() < 5:
            o = day.toordinal() % 97 + 100.0
            rows.append({"date": f"{day.isoformat()}T00:00:00", "open": o, "high": o + 2,
                         "low": o - 2, "close": o + 1, "adjusted_close": o + 1, "volume": 1000.0})
        day += timedelta(days=1)
    return rows, {}


async def hourly_bars(symbol, interval, start, end, *args, **kwargs):
    """Seven bars a weekday, opening 13:30 to 19:30 UTC."""
    rows, day, last = [], date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    while day <= last:
        if day.weekday() < 5:
            for hour in range(13, 20):
                o = day.toordinal() % 97 + hour
                rows.append({"date": f"{day.isoformat()}T{hour:02d}:30:00Z", "open": o,
                             "high": o + 1, "low": o - 1, "close": o + 0.5,
                             "adjusted_close": o + 0.5, "volume": 100.0})
        day += timedelta(days=1)
    return rows, {}


async def short_bars(*args, **kwargs):
    rows, meta = await weekday_bars(*args, **kwargs)
    return rows[-150:], meta


async def gappy_bars(*args, **kwargs):
    rows, meta = await weekday_bars(*args, **kwargs)
    middle = len(rows) - 20
    return rows[:middle] + [{**rows[middle], "close": None, "adjusted_close": None}] \
        + rows[middle + 1:], meta


async def crowded_bars(*args, **kwargs):
    rows, meta = await hourly_bars(*args, **kwargs)
    last = datetime.fromisoformat(rows[-1]["date"]) + timedelta(minutes=30)
    return rows + [{**rows[-1], "date": last.strftime("%Y-%m-%dT%H:%M:%SZ")}], meta


async def doubled_bars(*args, **kwargs):
    rows, meta = await weekday_bars(*args, **kwargs)
    return rows + [rows[-1]], meta


async def no_bars(*args, **kwargs):
    raise RuntimeError("upstream down")


def client(bars, monkeypatch):
    monkeypatch.setattr("app.main.build_series", bars)
    return TestClient(create_app(api_key="test-key"))


def get(bars, monkeypatch, query):
    return client(bars, monkeypatch).get("/widgets/bars?" + query)


def test_the_widget_is_valid_0_1_and_declares_a_grouped_interval(monkeypatch):
    spec = client(weekday_bars, monkeypatch).get("/widgets.json").json()["ta_bars"]
    assert spec["type"] == "table" and spec["endpoint"] == "widgets/bars"
    assert spec["data"]["dataKey"] == "rows"
    assert spec["data"]["portfolio"] == {
        "protocol": "bdobb.portfolio/0.1", "view": "timeseries", "x": "time",
        "y": ["close", "sma_20", "sma_50", "sma_200"], "interval": "param"}
    jsonschema.validate(spec["data"]["portfolio"], SCHEMA)
    params = {p["paramName"]: p for p in spec["params"]}
    assert list(params) == ["symbol", "interval"]
    assert params["interval"]["groupType"] == bars_widget.INTERVAL_GROUP == "chart.interval"
    assert params["interval"]["value"] == "1d"
    options = [o["value"] for o in params["interval"]["options"]]
    assert options == list(bars_widget.INTERVALS) == ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"]
    assert all(TOKEN.match(v) for v in options)


def test_daily_bars_are_dates_with_all_three_studies(monkeypatch):
    answer = get(weekday_bars, monkeypatch, "symbol=AAPL&interval=1d")
    assert answer.status_code == 200 and set(answer.json()) == {"rows"}
    rows = answer.json()["rows"]
    assert len(rows) > 300 and all(set(r) == COLUMNS for r in rows)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["time"]) for r in rows)
    assert [r["time"] for r in rows] == sorted({r["time"] for r in rows})
    assert rows[30]["sma_20"] == pytest.approx(sum(r["close"] for r in rows[11:31]) / 20)
    assert rows[250]["sma_200"] == pytest.approx(sum(r["close"] for r in rows[51:251]) / 200)


def test_intraday_bars_are_exact_utc_openings_spaced_by_the_interval(monkeypatch):
    rows = get(hourly_bars, monkeypatch, "symbol=AAPL&interval=1h").json()["rows"]
    assert rows and all(UTC.match(r["time"]) for r in rows)
    assert {r["time"][11:] for r in rows} <= {f"{h}:30:00Z" for h in range(13, 20)}
    times = [datetime.strptime(r["time"], "%Y-%m-%dT%H:%M:%SZ") for r in rows]
    assert all(b - a >= timedelta(hours=1) for a, b in zip(times, times[1:]))


@pytest.mark.parametrize("query, status", [
    ("symbol=AAPL&interval=2h", 400),                 # not listed: refused, never resampled
    ("symbol=AAPL&interval=1d&session=regular", 422), # not a declared key here
    ("symbol=AAPL&interval=1d&provider=eodhd", 422),
    ("symbol=AAPL&symbol=MSFT&interval=1d", 422),      # repeated
])
def test_a_refusal_is_a_4xx_with_detail_and_no_rows(monkeypatch, query, status):
    answer = get(weekday_bars, monkeypatch, query)
    assert answer.status_code == status
    assert "rows" not in answer.json() and answer.json()["detail"]


def test_an_upstream_failure_fails_the_whole_request(monkeypatch):
    answer = get(no_bars, monkeypatch, "symbol=AAPL&interval=1d")
    assert answer.status_code == 502 and answer.json() == {"detail": "bars unavailable"}


def test_too_little_history_for_sma_200_is_refused(monkeypatch):
    answer = get(short_bars, monkeypatch, "symbol=AAPL&interval=1d")
    assert answer.status_code == 422 and "sma_200" in answer.json()["detail"]


def test_a_missing_close_after_the_warm_up_refuses_the_request(monkeypatch):
    answer = get(gappy_bars, monkeypatch, "symbol=AAPL&interval=1d")
    assert answer.status_code == 422 and "rows" not in answer.json()


def test_bars_closer_than_the_interval_are_refused_with_the_bars_time(monkeypatch):
    answer = get(crowded_bars, monkeypatch, "symbol=AAPL&interval=1h")
    assert answer.status_code == 422 and "closer" in answer.json()["detail"]


def test_a_duplicated_bar_is_refused(monkeypatch):
    answer = get(doubled_bars, monkeypatch, "symbol=AAPL&interval=1d")
    assert answer.status_code == 422 and "ascending" in answer.json()["detail"]


def test_the_latest_rows_are_kept_at_the_cap(monkeypatch):
    whole = get(weekday_bars, monkeypatch, "symbol=AAPL&interval=1d").json()["rows"]
    monkeypatch.setattr(bars_widget, "MAX_ROWS", 100)
    capped = get(weekday_bars, monkeypatch, "symbol=AAPL&interval=1d").json()["rows"]
    assert capped == whole[-100:]


def test_the_bars_are_read_only(monkeypatch):
    assert client(weekday_bars, monkeypatch).post("/widgets/bars").status_code == 405
