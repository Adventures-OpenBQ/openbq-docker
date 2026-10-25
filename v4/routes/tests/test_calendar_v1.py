# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v1 calendar routes, mounted on a bare FastAPI router.

`register` only ever touches `router.api_router`, so the routes are tested here without
openbb-core's provider registry, which refuses to load on a host carrying a stale OpenBB
extension. The legacy envelope is tested through `openbq_calendar.legacy`, where it lives.
"""

import asyncio
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from openbq_calendar.legacy import build
from openbq_routes import calendar_v1
from openbq_routes.calendar_v1 import register

stub = SimpleNamespace(api_router=APIRouter())
register(stub)
app = FastAPI()
app.include_router(stub.api_router, prefix="/api/v1/calendar")
client = TestClient(app)
BUNDLE = "/api/v1/calendar/trading/v1/bundle"
CALENDARS_ROUTE = "/api/v1/calendar/trading/v1/calendars"


def test_v1_capabilities_and_per_day_boundaries():
    r = client.get(CALENDARS_ROUTE)
    assert r.status_code == 200
    assert "exchange:XHKG" in [c["calendarId"] for c in r.json()["calendars"]]
    r = client.get(BUNDLE, params={"calendar_id": "exchange:XHKG", "start": "2026-01-02", "end": "2026-01-02"})
    assert r.status_code == 200
    day = next(d for d in r.json()["days"] if d["date"] == "2026-01-02")
    assert len(day["segments"]) == 2


def test_invalid_calendar_and_ranges_fail_without_fallback():
    for params in [
        {"calendar_id": "constructor", "start": "2026-01-01", "end": "2026-01-02"},
        {"calendar_id": "exchange:XNYS", "start": "2026-02-02", "end": "2026-01-01"},
    ]:
        assert client.get(BUNDLE, params=params).status_code == 422


def test_legacy_envelope_retains_early_close_and_holiday_names():
    body = build("XNYS", 2026)["data"]
    assert body["ExchangeHolidays"]["2026-07-03"]["Holiday"] == "July 4th"
    assert body["ExchangeHolidays"]["2026-11-27"]["EarlyClose"] == "13:00:00"


def test_capabilities_report_supplier_bounds_for_exactly_the_qualified_set():
    import exchange_calendars as xc

    from openbq_calendar.registry import CALENDARS

    entries = {c["calendarId"]: c for c in client.get(CALENDARS_ROUTE).json()["calendars"]}
    assert set(entries) == {"exchange:" + name for name in CALENDARS}
    assert len(entries) == 71
    assert entries["exchange:24/7"]["timezone"] == "UTC"
    assert entries["exchange:XSES"]["end"] == "2026-12-31"
    assert entries["exchange:XSHG"]["start"] == "1990-12-03"
    tokyo = type(xc.get_calendar("XTKS")).bound_min().date().isoformat()
    assert entries["exchange:XTKS"]["start"] == tokyo
    assert entries["exchange:XTAI"]["start"] == "2019-01-01"
    assert entries["exchange:XHKG"]["end"] == "2040-12-31"


def test_requests_inside_one_year_share_one_whole_year_build(monkeypatch):
    calendar_v1.clear_cache()
    calls = []
    real = calendar_v1.generate_bundle

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(calendar_v1, "generate_bundle", counting)
    for start in ("2026-01-02", "2026-03-01"):
        r = client.get(BUNDLE, params={"calendar_id": "exchange:XNYS", "start": start, "end": "2026-06-30"})
        assert r.status_code == 200
        assert r.json()["coverage"] == {"start": "2026-01-01", "end": "2026-12-31", "complete": True}
    # "XNYS" and "exchange:XNYS" are one calendar, so one cache key.
    assert (
        client.get(BUNDLE, params={"calendar_id": "XNYS", "start": "2026-05-05", "end": "2026-05-05"}).status_code
        == 200
    )
    assert len(calls) == 1


def test_the_cache_stays_inside_its_byte_budget(monkeypatch):
    monkeypatch.setattr(calendar_v1, "CACHE_BYTES", 300_000)
    calendar_v1.clear_cache()
    for year in range(2020, 2027):
        calendar_v1.build_bundle("exchange:XNYS", year, year)
    assert calendar_v1.cached_bytes() <= 300_000
    assert 1 <= calendar_v1.cached_entries() < 7


def test_capabilities_are_built_once_and_off_the_event_loop(monkeypatch):
    calendar_v1._capabilities.cache_clear()
    on_loop = []
    real = calendar_v1.bounds

    def watching(name):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(name)

    monkeypatch.setattr(calendar_v1, "bounds", watching)
    client.get(CALENDARS_ROUTE)
    client.get(CALENDARS_ROUTE)
    assert len(on_loop) == len(calendar_v1.CALENDARS) and not any(on_loop)


def test_an_oversize_span_is_refused_before_anything_is_built(monkeypatch):
    calendar_v1.clear_cache()
    built = []
    monkeypatch.setattr(calendar_v1, "generate_bundle", lambda *a, **k: built.append(a))
    r = client.get(BUNDLE, params={"calendar_id": "exchange:XNYS", "start": "2000-01-01", "end": "2020-12-31"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "RESOURCE_LIMIT"
    assert built == [] and calendar_v1.cached_entries() == 0


def test_bundles_for_library_names_and_clipped_years():
    calendar_v1.clear_cache()
    r = client.get(BUNDLE, params={"calendar_id": "exchange:24/7", "start": "2026-01-03", "end": "2026-01-03"})
    assert r.status_code == 200 and r.json()["calendarId"] == "exchange:24/7"
    r = client.get(BUNDLE, params={"calendar_id": "exchange:XSHG", "start": "1990-12-03", "end": "1990-12-31"})
    assert r.status_code == 200 and r.json()["coverage"]["start"] == "1990-12-03"
    r = client.get(BUNDLE, params={"calendar_id": "exchange:XSES", "start": "2026-12-01", "end": "2026-12-31"})
    assert r.status_code == 200 and r.json()["coverage"]["end"] == "2026-12-31"
    gone = {"calendar_id": "exchange:XSES", "start": "2027-01-04", "end": "2027-01-04"}
    assert client.get(BUNDLE, params=gone).status_code == 422


def test_calendar_v1_routes_remain_documented_but_are_not_workspace_widgets():
    paths = app.openapi()["paths"]
    for path in (CALENDARS_ROUTE, BUNDLE):
        assert paths[path]["get"].get("widget_config") == {"exclude": True}, path
