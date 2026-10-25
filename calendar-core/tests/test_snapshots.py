# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Qualification of the full set (spec "Qualification").

Every calendar has a generated snapshot of its 2026 sessions, tied to the catalogue it came from, with evidence
library_baseline: it pins the library's output against drift. The major exchanges also carry facts checked by hand
against their own published 2026 calendars. Each fact names its source. Where an exchange and the library disagree, the
fact is not edited to match: the disagreement is reported (see the plan's "Library disagreements").
"""

import json
from pathlib import Path

import pytest

from openbq_calendar.catalogue import snapshot_bytes, snapshot_path
from openbq_calendar.registry import CALENDARS

SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize("name", CALENDARS)
def test_the_snapshot_matches(name):
    assert json.loads(snapshot_bytes(name)) == json.loads(snapshot_path(SNAPSHOTS, name).read_bytes())


def test_one_snapshot_per_calendar_and_nothing_else():
    expected = sorted(snapshot_path(SNAPSHOTS, name).name for name in CALENDARS)
    assert sorted(p.name for p in SNAPSHOTS.glob("*.json")) == expected


def test_every_snapshot_is_library_baseline():
    for name in CALENDARS:
        assert json.loads(snapshot_path(SNAPSHOTS, name).read_bytes())["evidence"] == ["library_baseline"], name


# mic -> {date: "closed" | (open UTC, close UTC) | (open, close, break start, break end)}
SPOT = {
    # Euronext 2026 trading calendar: Good Friday, Easter Monday; 14:05 CET close on Christmas Eve.
    "XPAR": {
        "2026-04-03": "closed",
        "2026-04-06": "closed",
        "2026-12-24": ("2026-12-24T08:00:00Z", "2026-12-24T13:05:00Z"),
    },
    # Deutsche Börse Xetra 2026 trading calendar: Good Friday, Labour Day closed; Whit Monday trades 09:00-17:30 CEST.
    "XETR": {
        "2026-04-03": "closed",
        "2026-05-01": "closed",
        "2026-05-25": ("2026-05-25T07:00:00Z", "2026-05-25T15:30:00Z"),
    },
    # SIX Swiss Exchange 2026 trading calendar: Berchtoldstag, Ascension, Whit Monday.
    "XSWX": {"2026-01-02": "closed", "2026-05-14": "closed", "2026-05-25": "closed"},
    # SSE 2026 holiday notice: Spring Festival closure Feb 16-23, National Day Oct 1-7; SSE trading rules: 09:30-11:30
    # and 13:00-15:00 CST.
    "XSHG": {
        "2026-02-16": "closed",
        "2026-02-23": "closed",
        "2026-02-24": ("2026-02-24T01:30:00Z", "2026-02-24T07:00:00Z", "2026-02-24T03:30:00Z", "2026-02-24T05:00:00Z"),
        "2026-10-01": "closed",
        "2026-10-08": ("2026-10-08T01:30:00Z", "2026-10-08T07:00:00Z", "2026-10-08T03:30:00Z", "2026-10-08T05:00:00Z"),
    },
    # KRX 2026 market holidays: the year's first session opens 10:00 KST; Seollal; Chuseok; year-end closure.
    "XKRX": {
        "2026-01-02": ("2026-01-02T01:00:00Z", "2026-01-02T06:30:00Z"),
        "2026-02-17": "closed",
        "2026-09-25": "closed",
        "2026-12-31": "closed",
    },
    # BSE 2026 trading holidays: Republic Day, Gandhi Jayanti; regular session 09:15-15:30 IST.
    "XBOM": {
        "2026-01-26": "closed",
        "2026-10-02": "closed",
        "2026-01-05": ("2026-01-05T03:45:00Z", "2026-01-05T10:00:00Z"),
    },
    # SGX 2026 trading calendar: Chinese New Year (two days), National Day observed on the Monday.
    "XSES": {"2026-02-17": "closed", "2026-02-18": "closed", "2026-08-10": "closed"},
    # B3 2026 calendar: Carnival Monday and Tuesday, Tiradentes, Corpus Christi.
    "BVMF": {"2026-02-16": "closed", "2026-02-17": "closed", "2026-04-21": "closed", "2026-06-04": "closed"},
    # BMV 2026 calendar: Constitution Day, Juárez's birthday, Revolution Day (each a Monday observance).
    "XMEX": {"2026-02-02": "closed", "2026-03-16": "closed", "2026-11-16": "closed"},
    # JSE 2026 public holidays: Freedom Day, Youth Day, Women's Day observed on the Monday.
    "XJSE": {"2026-04-27": "closed", "2026-06-16": "closed", "2026-08-10": "closed"},
    # ASX 2026 trading calendar: Australia Day, King's Birthday; Anzac Day falls on a Saturday with no Monday holiday,
    # so 2026-04-27 trades 10:00-16:00 AEST.
    "XASX": {
        "2026-01-26": "closed",
        "2026-06-08": "closed",
        "2026-04-27": ("2026-04-27T00:00:00Z", "2026-04-27T06:00:00Z"),
    },
    # CME Globex: the week opens Sunday 17:00 CT (CST in January, CDT after 2026-03-08); Christmas closed. The close is
    # the library's 17:00 convention with no maintenance break, which the spec adopts.
    "CMES": {
        "2026-01-05": ("2026-01-04T23:00:00Z", "2026-01-05T23:00:00Z"),
        "2026-03-09": ("2026-03-08T22:00:00Z", "2026-03-09T22:00:00Z"),
        "2026-12-25": "closed",
    },
}


@pytest.mark.parametrize("mic", sorted(SPOT))
def test_hand_checked_facts(mic):
    sessions = {row[0]: tuple(row[1:]) for row in json.loads(snapshot_path(SNAPSHOTS, mic).read_bytes())["sessions"]}
    for day, expected in SPOT[mic].items():
        if expected == "closed":
            assert day not in sessions, day
        else:
            assert sessions.get(day, ())[: len(expected)] == expected, day
