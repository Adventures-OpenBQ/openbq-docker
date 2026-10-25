# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Figure construction."""

import json
from datetime import datetime

import pandas as pd

from app.figure import build_figure

BARS = [
    {"date": "2024-01-02", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
    {"date": "2024-01-03", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0},
]


def test_figure_has_one_trace_with_every_bar():
    fig = build_figure("AAPL", BARS)
    assert len(fig["data"]) == 1
    assert len(fig["data"][0]["x"]) == 2


def test_symbol_appears_in_the_title():
    assert "AAPL" in fig_title(build_figure("AAPL", BARS))


def fig_title(fig):
    title = fig["layout"]["title"]
    return title["text"] if isinstance(title, dict) else title


def test_empty_bars_still_produce_a_valid_figure():
    fig = build_figure("AAPL", [])
    assert fig["data"][0]["x"] == []


def test_tick_built_bars_with_datetimes_serialise():
    """Live bars from kdb+ carry datetimes; /chart must still return JSON, not a 500."""
    bars = BARS + [dict(BARS[1], date=pd.Timestamp("2026-10-20")),
                   dict(BARS[1], date=datetime(2026, 10, 20, 15, 13))]
    fig = json.loads(json.dumps(build_figure("AAPL", bars)))
    assert fig["data"][0]["x"] == ["2024-01-02", "2024-01-03",
                                   "2026-10-20T00:00:00", "2026-10-20T15:13:00"]
