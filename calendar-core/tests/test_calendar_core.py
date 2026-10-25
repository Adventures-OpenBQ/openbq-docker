# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
from datetime import date, datetime, timedelta, timezone
import copy
import pytest
from openbq_calendar.contracts import validate_bundle
from openbq_calendar.canonical import bundle_digest
from openbq_calendar.supplier import generate_bundle
from openbq_calendar.registry import CALENDARS, bounds


def make():
    return generate_bundle(
        "exchange:XNYS", date(2026, 11, 25), date(2026, 11, 28), generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )


def test_actual_supplier_keeps_closed_day_and_early_close():
    b = make()
    assert [d["state"] for d in b["days"]] == ["open", "closed", "open", "closed"]
    assert b["days"][2]["close"] == "2026-11-27T18:00:00Z"
    assert b["days"][2]["evidenceStatus"] == "library_baseline"
    assert b["coverage"] == {"start": "2026-11-25", "end": "2026-11-28", "complete": True}


def test_hong_kong_keeps_both_segments():
    b = generate_bundle("exchange:XHKG", date(2026, 1, 2), date(2026, 1, 2), generated_at=datetime.now(timezone.utc))
    assert b["days"][0]["segments"] == [
        {"start": "2026-01-02T01:30:00Z", "end": "2026-01-02T04:00:00Z"},
        {"start": "2026-01-02T05:00:00Z", "end": "2026-01-02T08:00:00Z"},
    ]


def test_content_hash_excludes_delivery_time_not_schedule():
    b = make()
    c = copy.deepcopy(b)
    c["generatedAt"] = "2026-02-01T00:00:00Z"
    assert bundle_digest(b) == bundle_digest(c)
    c["days"][0]["close"] = "2026-11-25T20:00:00Z"
    assert bundle_digest(b) != bundle_digest(c)


@pytest.mark.parametrize("mutation", ["unknown", "gap", "bad_date", "segments", "false_final", "digest"])
def test_contract_rejects_unsafe_or_misleading_bundle(mutation):
    b = make()
    if mutation == "unknown":
        b["surprise"] = 1
    if mutation == "gap":
        b["days"].pop()
    if mutation == "bad_date":
        b["days"][0]["date"] = "2026-02-30"
    if mutation == "segments":
        b["days"][0]["segments"][0]["end"] = "2026-11-25T13:00:00Z"
    if mutation == "false_final":
        b["days"][0]["evidenceStatus"] = "market_final"
    if mutation == "digest":
        b["digest"] = "0" * 64
    with pytest.raises(ValueError):
        validate_bundle(b)


def test_unknown_alias_never_becomes_new_york():
    with pytest.raises(ValueError):
        generate_bundle("constructor", date(2026, 1, 1), date(2026, 1, 2), generated_at=datetime.now(timezone.utc))


def test_complete_closed_only_day():
    b = generate_bundle("exchange:XNYS", date(2026, 1, 1), date(2026, 1, 1), generated_at=datetime.now(timezone.utc))
    assert b["days"][0]["state"] == "closed" and b["coverage"]["complete"]


def test_artifact_exports_hash_verified_resources(tmp_path):
    from openbq_calendar.artifact import export_contract
    import json
    import hashlib

    report = export_contract(tmp_path)
    assert report["contractVersion"] == 1
    for f in report["files"]:
        assert hashlib.sha256((tmp_path / f["path"]).read_bytes()).hexdigest() == f["sha256"]
    assert json.loads((tmp_path / "calendar-v1.schema.json").read_text())["additionalProperties"] is False


def test_taiwan_makeup_days_do_not_imply_exchange_open():
    b = generate_bundle("exchange:XTAI", date(2025, 2, 7), date(2025, 2, 10), generated_at=datetime.now(timezone.utc))
    assert [d["state"] for d in b["days"]] == ["open", "closed", "closed", "open"]


def test_taiwan_pre2019_history_is_not_falsely_certified():
    with pytest.raises(ValueError, match="historical"):
        generate_bundle(
            "exchange:XTAI", date(2018, 12, 21), date(2018, 12, 24), generated_at=datetime.now(timezone.utc)
        )


def test_payment_calendar_is_distinct_from_exchange(tmp_path):
    b = make()
    b["calendarId"] = "payment:US-FEDWIRE"
    b["kind"] = "currency_payment"
    b["currency"] = "USD"
    b["days"][1].update(
        state="closed",
        evidenceStatus="operator_final",
        evidence=[
            {
                "id": "fed-notice",
                "kind": "payment_operator_notice",
                "domain": "settlement",
                "references": ["retained:notice"],
            }
        ],
    )
    b["digest"] = bundle_digest(b)
    assert validate_bundle(b)["kind"] == "currency_payment"
    b["days"][1]["evidence"][0]["kind"] = "religious_notice"
    b["digest"] = bundle_digest(b)
    with pytest.raises(ValueError):
        validate_bundle(b)


def test_range_before_the_supplier_bound_is_refused():
    # exchange_calendars builds Tokyo from 1997 only; asking earlier is an error, never a guess.
    with pytest.raises(ValueError, match="before 1997-01-01"):
        generate_bundle("exchange:XTKS", date(1996, 12, 30), date(1997, 1, 6), generated_at=datetime.now(timezone.utc))


def test_bounds_come_from_the_supplier_inside_the_route_window():
    from openbq_calendar.registry import bounds

    assert bounds("XTKS") == (date(1997, 1, 1), date(2040, 12, 31))
    assert bounds("XHKG") == (date(1990, 1, 1), date(2040, 12, 31))  # supplier 1960-2049, clipped
    assert bounds("XTAI")[0] == date(2019, 1, 1)  # qualification, not supplier


@pytest.mark.parametrize("name", CALENDARS)
def test_every_catalogue_calendar_builds_inside_its_bounds_and_refuses_outside(name):
    low, high = bounds(name)
    now = datetime.now(timezone.utc)
    first = generate_bundle("exchange:" + name, low, low + timedelta(days=6), generated_at=now)
    last = generate_bundle("exchange:" + name, high - timedelta(days=6), high, generated_at=now)
    assert first["coverage"]["start"] == low.isoformat()
    assert last["coverage"]["end"] == high.isoformat()
    with pytest.raises(ValueError):
        generate_bundle("exchange:" + name, low - timedelta(days=1), low, generated_at=now)
    with pytest.raises(ValueError):
        generate_bundle("exchange:" + name, high, high + timedelta(days=1), generated_at=now)


def test_cme_monday_opens_on_sunday_evening_in_chicago():
    b = generate_bundle("exchange:CMES", date(2026, 1, 4), date(2026, 1, 5), generated_at=datetime.now(timezone.utc))
    assert [d["state"] for d in b["days"]] == ["closed", "open"]
    assert (b["days"][1]["open"], b["days"][1]["close"]) == ("2026-01-04T23:00:00Z", "2026-01-05T23:00:00Z")


def test_calendar_ids_allow_the_library_names_and_nothing_looser():
    b = generate_bundle("exchange:24/7", date(2026, 1, 3), date(2026, 1, 3), generated_at=datetime.now(timezone.utc))
    assert b["calendarId"] == "exchange:24/7" and b["days"][0]["state"] == "open"
    bad = make()
    bad["calendarId"] = "exchange:A B"
    bad["digest"] = bundle_digest(bad)
    with pytest.raises(ValueError):
        validate_bundle(bad)
