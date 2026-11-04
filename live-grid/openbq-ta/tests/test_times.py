# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Time parameters (spec 2026-11-04 §2): ISO instants, OBS-n, and refusals."""
from datetime import datetime, timezone

import polars as pl
import pytest

from openbq_ta import studies
from openbq_ta.compute import compute
from openbq_ta.registry import StudyError, get, resolve
from openbq_ta.times import resolve_time
from tests.ta_helpers import fixture_frame

UTC = timezone.utc
TRADES = ["2026-06-03T14:00:03Z", "2026-06-03T14:00:02Z", datetime(2026, 6, 3, 14, 0, 1)]


@pytest.mark.parametrize("value, expected", [
    ("2026-06-03T14:00:00Z", datetime(2026, 6, 3, 14, tzinfo=UTC)),
    ("2026-06-03T10:00:00-04:00", datetime(2026, 6, 3, 14, tzinfo=UTC)),
    ("2026-06-03T14:00:00", datetime(2026, 6, 3, 14, tzinfo=UTC)),   # naive is UTC
    ("2026-06-03", datetime(2026, 6, 3, tzinfo=UTC)),
    ("OBS-1", datetime(2026, 6, 3, 14, 0, 3, tzinfo=UTC)),
    ("OBS-3", datetime(2026, 6, 3, 14, 0, 1, tzinfo=UTC)),
])
def test_an_instant_or_obs_resolves_to_utc(value, expected):
    assert resolve_time(value, TRADES) == expected


@pytest.mark.parametrize("value", ["T-1bd@open", "now-1h", "OBS-0", "OBS-4", "", "S"])
def test_anything_else_is_a_study_error(value):
    with pytest.raises(StudyError):
        resolve_time(value, TRADES)


def test_an_aware_datetime_passes_through_as_utc():
    at = datetime(2026, 6, 3, 10, tzinfo=timezone.utc)
    assert resolve_time(at) == at


def test_avwap_declares_its_anchor_a_time_and_keeps_its_column_name():
    assert get("avwap").times == ("anchor",)
    req = resolve("avwap", anchor="2026-06-03T14:00:00Z")
    frame = fixture_frame()
    assert "avwap|anchor=2026-06-03T14:00:00Z" in compute(frame, [req]).columns


def test_an_unresolvable_time_drops_that_study_with_a_note_and_computes_the_rest():
    notes = []
    reqs = [resolve("avwap", anchor="T-1bd@open"), resolve("sma", period=5)]
    out = compute(fixture_frame(), reqs, notes=notes)
    assert "sma|period=5" in out.columns
    assert not any(c.startswith("avwap") for c in out.columns)
    assert [(r.name, "host resolves" in m) for r, m in notes] == [("avwap", True)]


def test_obs_beyond_the_trades_held_drops_the_study_with_a_note():
    notes = []
    compute(fixture_frame(), [resolve("avwap", anchor="OBS-9")], trades=TRADES, notes=notes)
    assert "3 trades" in notes[0][1]


def test_without_notes_an_unresolvable_time_raises_as_before():
    with pytest.raises(StudyError):
        compute(fixture_frame(), [resolve("avwap", anchor="now-1h")])


def test_a_failing_iterate_is_dropped_with_a_note_and_the_rest_computes():
    def boom(frame, params):
        raise ZeroDivisionError("bad bar")
    studies.study(name="t_boom", label="Boom", params={}, colors={"b": "#fff"}, iterate=boom)
    try:
        notes = []
        out = compute(fixture_frame(), [resolve("t_boom"), resolve("sma", period=5)], notes=notes)
        assert "sma|period=5" in out.columns and "b" not in out.columns
        assert notes[0][0].name == "t_boom" and "bad bar" in notes[0][1]
    finally:
        studies.unload("<runtime>")


def test_an_iterate_missing_an_output_is_dropped_with_a_note():
    studies.study(name="t_short", label="Short", params={}, colors={"a": "#fff", "b": "#000"},
                  iterate=lambda f, p: {"a": [0.0] * f.height})
    try:
        notes = []
        compute(fixture_frame(), [resolve("t_short")], notes=notes)
        assert "['b']" in notes[0][1]
    finally:
        studies.unload("<runtime>")


def test_a_failing_session_agg_is_dropped_with_a_note():
    @studies.study(name="t_badsess", label="Bad", params={}, colors={"x": "#fff"},
                   session_agg=lambda p: {"C": pl.col("nope").last()})
    def bad(p):
        return [pl.col("C").alias("x")]
    try:
        notes = []
        compute(fixture_frame(), [resolve("t_badsess")], notes=notes)
        assert notes and notes[0][0].name == "t_badsess"
    finally:
        studies.unload("<runtime>")


def test_a_time_parameter_reaches_a_folder_study_as_a_datetime():
    seen = {}

    @studies.study(name="t_since", label="Since", params={"start": None}, colors={"s": "#fff"},
                   times=("start",))
    def since(p):
        seen["start"] = p["start"]
        return [pl.col("close").alias("s")]
    try:
        compute(fixture_frame(), [resolve("t_since", start="2026-06-03T14:00:00Z")])
        assert seen["start"] == datetime(2026, 6, 3, 14, tzinfo=UTC)
    finally:
        studies.unload("<runtime>")


def test_exprs_of_and_deps_of_resolve_time_parameters():
    assert "avwap" in studies.exprs_of("avwap", anchor="2026-06-03T14:00:00Z")
    studies.study(name="t_nest", label="Nest", params={"start": None}, colors={"s": "#fff"},
                  times=("start",), deps=lambda p: [])(lambda p: [pl.lit((p["start"] or datetime(2000, 1, 1)).year).alias("s")])
    try:
        assert studies.deps_of("t_nest", start="2026-06-03T14:00:00Z") == []
        assert studies.exprs_of("t_nest", start="2026-06-03T14:00:00Z")["s"] is not None
    finally:
        studies.unload("<runtime>")
