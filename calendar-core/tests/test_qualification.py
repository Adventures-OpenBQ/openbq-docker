# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The retained bundle fixtures state published facts (review I6); tests/test_snapshots.py qualifies the full set.

Qualified means a retained conformance bundle that states facts taken from the exchange's
own published holiday schedule: a closure, an early close or a changed trading week. The
library agreeing with itself is not qualification, so each fact is written out here.
"""

import json
from pathlib import Path

import pytest

import openbq_calendar
from openbq_calendar.contracts import validate_bundle
from openbq_calendar.registry import CALENDARS

CONFORMANCE = Path(openbq_calendar.__file__).parent / "resources" / "conformance"

# fixture -> {date: "closed" or (open UTC, close UTC)}
FACTS = {
    "XNYS.json": {"2026-11-26": "closed", "2026-11-27": ("2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z")},
    "XNYS-2026-12.json": {
        "2026-12-24": ("2026-12-24T14:30:00Z", "2026-12-24T18:00:00Z"),  # 13:00 early close
        "2026-12-25": "closed",
        "2026-12-28": ("2026-12-28T14:30:00Z", "2026-12-28T21:00:00Z"),
        "2027-01-01": "closed",
    },
    "XLON.json": {
        "2026-12-24": ("2026-12-24T08:00:00Z", "2026-12-24T12:30:00Z"),  # Christmas Eve half day
        "2026-12-25": "closed",
        "2026-12-28": "closed",  # Boxing Day falls on a Saturday; the holiday is the Monday
        "2026-12-31": ("2026-12-31T08:00:00Z", "2026-12-31T12:30:00Z"),
        "2027-01-01": "closed",
    },
    "XTSE.json": {"2026-12-25": "closed", "2026-12-28": "closed", "2027-01-01": "closed"},
    "XETR.json": {"2026-12-24": "closed", "2026-12-25": "closed", "2026-12-31": "closed"},
    "XTKS.json": {"2026-12-30": ("2026-12-30T00:00:00Z", "2026-12-30T06:30:00Z"), "2026-12-31": "closed"},
    "XASX.json": {
        "2026-12-24": ("2026-12-23T23:00:00Z", "2026-12-24T03:10:00Z"),  # 14:10 early close
        "2026-12-25": "closed",
        "2026-12-28": "closed",
    },
    "XTAE.json": {
        "2026-01-02": "closed",  # the last Friday before TASE moved to Monday-Friday
        "2026-01-05": ("2026-01-05T07:59:00Z", "2026-01-05T15:15:00Z"),
        "2026-01-09": ("2026-01-09T07:59:00Z", "2026-01-09T11:50:00Z"),  # the short Friday session
    },
    "XHKG.json": {"2026-01-02": ("2026-01-02T01:30:00Z", "2026-01-02T08:00:00Z")},
    "XTAI.json": {
        "2025-02-08": "closed",
        "2025-02-09": "closed",
        "2025-02-10": ("2025-02-10T01:00:00Z", "2025-02-10T05:30:00Z"),
    },
    "XPAR.json": {
        "2026-12-24": ("2026-12-24T08:00:00Z", "2026-12-24T13:05:00Z"),  # Euronext 14:05 CET Christmas Eve close
        "2026-12-25": "closed",
        "2026-12-31": ("2026-12-31T08:00:00Z", "2026-12-31T13:05:00Z"),  # and New Year's Eve
        "2027-01-01": "closed",
    },
    "XKRX.json": {
        "2026-12-25": "closed",
        "2026-12-31": "closed",  # KRX year-end closure
        "2027-01-04": ("2027-01-04T01:00:00Z", "2027-01-04T06:30:00Z"),  # the year's first session opens 10:00 KST
    },
    "CMES-2026-01.json": {
        "2026-01-04": "closed",  # a Sunday is no session label ...
        "2026-01-05": ("2026-01-04T23:00:00Z", "2026-01-05T23:00:00Z"),  # ... Monday's session opens Sunday 17:00 CT
    },
}


def load(filename):
    return validate_bundle(json.loads((CONFORMANCE / filename).read_text()))


def test_every_fixture_is_a_served_calendar_and_the_first_nine_keep_theirs():
    covered = {load(filename)["calendarId"] for filename in FACTS}
    assert covered <= {"exchange:" + name for name in CALENDARS}
    nine = ("XNYS", "XLON", "XHKG", "XTKS", "XASX", "XTAE", "XTSE", "XETR", "XTAI")
    assert {"exchange:" + name for name in nine} <= covered


@pytest.mark.parametrize("filename", sorted(FACTS))
def test_fixture_states_the_published_facts(filename):
    days = {d["date"]: d for d in load(filename)["days"]}
    for day, expected in FACTS[filename].items():
        if expected == "closed":
            assert days[day]["state"] == "closed", day
        else:
            assert (days[day]["open"], days[day]["close"]) == expected, day
