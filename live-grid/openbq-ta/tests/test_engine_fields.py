# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Engine fields carried in from Art's Charts' engine (spec S12)."""
from datetime import datetime

import polars as pl
import pytest

from openbq_ta.compute import compute, session_columns
from openbq_ta.iterative import parabolic_sar
from openbq_ta.registry import REGISTRY, Indicator, Req, StudyError, col_suffix, get, resolve
from tests.ta_helpers import fixture_frame

WINDOWS = {
    "sma": ("period",), "ema": ("period",), "rsi": ("period",), "bbands": ("period",),
    "atr": ("period",), "wma": ("period",), "keltner": ("period", "atr_period"),
    "donchian": ("period",), "vwap": (), "avwap": (), "volume": (),
    "macd": ("fast", "slow", "signal"), "stoch": ("k", "smooth_k", "d"),
    "stochrsi": ("period", "stoch_period"), "adx": ("period",), "cci": ("period",),
    "willr": ("period",), "roc": ("period",), "obv": (), "stddev": ("period",),
    "pct_b": ("period",), "bandwidth": ("period",), "sar": (),
}


def test_every_built_in_declares_its_windows():
    assert {name: ind.windows for name, ind in REGISTRY.items()} == WINDOWS


def test_source_and_units_are_part_of_a_requests_identity():
    assert col_suffix(resolve("sma", period=50)) == "|period=50"
    assert col_suffix(resolve("sma", "eodhd", period=50)) == "|period=50,source=eodhd"
    assert col_suffix(resolve("sma", None, {"period": "bd"}, period=50)) == "|period=50bd"


def test_resolve_refuses_a_bad_source_a_stray_unit_and_a_partial_unit():
    with pytest.raises(ValueError, match="source"):
        resolve("sma", "yahoo")
    with pytest.raises(ValueError, match="takes no unit"):
        resolve("bbands", None, {"k": "bd"})
    with pytest.raises(ValueError, match="all of 'macd' or none"):
        resolve("macd", None, {"fast": "bd"})


def test_sar_runs_through_its_iterate_field():
    assert get("sar").iterate is parabolic_sar and get("sar").iterative
    assert "sar|acceleration=0.02,maximum=0.2" in compute(fixture_frame(), [resolve("sar")]).columns


def test_a_study_error_is_a_value_error():
    assert issubclass(StudyError, ValueError)


def test_a_sessioned_indicator_reads_the_prior_session(monkeypatch):
    from openbq_ta.registry import register
    ind = Indicator(
        name="t_prior_high", label="t", params={"anchor": "1d", "session_shift": 1},
        pane="price", price_basis="raw", convention="test",
        deps=lambda p: [], build=lambda p, b: [pl.col("H").alias("prior_high")],
        render={"prior_high": {"type": "line", "color": None}},
        sessioned=True, session_agg=lambda p: {"H": pl.col("high").max()},
    )
    register(ind)
    try:
        frame = pl.DataFrame({
            "date": pl.datetime_range(datetime(2026, 1, 5), datetime(2026, 1, 7, 12),
                                      "12h", eager=True),
            "high": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })
        out = compute(frame, [Req("t_prior_high", dict(ind.params))])
        assert out["prior_high|anchor=1d,session_shift=1"].to_list() == [None, None, 2.0, 2.0, 4.0, 4.0]
    finally:
        REGISTRY.pop("t_prior_high")


def _fake_sessioned() -> Indicator:
    """A sessioned indicator that is NOT registered.

    REGISTRY is module-global, so registering a test-only indicator would
    leak into every other test module's view of it -- including the
    convention sweep. session_columns takes the Indicator directly, so it
    needs no registration.
    """
    return Indicator(
        name="_test_session", label="Test session",
        params={"anchor": "1d", "session_shift": 1},
        pane="price", price_basis="raw", convention="test only",
        deps=lambda p: [],
        build=lambda p, b: [((pl.col("H") + pl.col("L") + pl.col("C")) / 3).alias("mid")],
        render={"mid": {"type": "line", "color": None}},
        sessioned=True,
        session_agg=lambda p: {
            "H": pl.col("high").max(), "L": pl.col("low").min(),
            "C": pl.col("close").last(),
        },
    )


def _intraday(days: int = 3, per_day: int = 8) -> pl.DataFrame:
    rows = []
    for day in range(1, days + 1):
        for step in range(per_day):
            price = 100.0 + day * 10 + step
            rows.append({
                "date": datetime(2026, 1, day, 9 + step),
                "open": price, "high": price + 1, "low": price - 1,
                "close": price, "adj_close": price,
                "volume": 100.0, "vwap": price,
            })
    return pl.DataFrame(rows)


def test_session_columns_holds_the_prior_sessions_values_flat():
    ind = _fake_sessioned()
    out = session_columns(_intraday(), ind, ind.params)
    mid = out["mid"]
    # Day 1 has no prior session.
    assert all(v is None for v in mid[:8])
    # Day 2 holds one value across all eight of its bars.
    assert len(set(mid[8:16])) == 1 and mid[8] is not None
    # Day 3 holds a different one.
    assert mid[16] != mid[8]


def test_session_columns_returns_one_value_per_row_for_an_ascending_frame():
    frame = _intraday()
    ind = _fake_sessioned()
    out = session_columns(frame, ind, ind.params)
    assert len(out["mid"]) == frame.height


def test_session_columns_raises_rather_than_silently_mis_assign_an_unsorted_frame():
    """The returned lists are assigned straight onto the caller's frame by row
    position, so they must align with ITS rows. session_columns does not sort
    internally -- group_by_dynamic refuses unsorted input and raises here. If
    an internal sort were ever added, this call would succeed instead, and the
    now-reordered lists would be assigned onto the frame's original (unsorted)
    row order, silently mis-assigning every value."""
    frame = _intraday().reverse()
    ind = _fake_sessioned()
    with pytest.raises(pl.exceptions.InvalidOperationError, match="not sorted"):
        session_columns(frame, ind, ind.params)


def test_a_plain_indicator_declares_sessioned_false():
    assert get("sma").sessioned is False
    assert get("sma").session_agg is None


def test_session_columns_raises_when_build_omits_a_promised_render_column():
    """render promises 'mid' and 'phantom'; build only produces 'mid'. A
    silently-dropped output means a chart series never appears with no signal
    as to why -- this must fail loudly instead."""
    ind = _fake_sessioned()
    broken = Indicator(
        name="_test_session_broken", label="Broken", params=ind.params,
        pane=ind.pane, price_basis=ind.price_basis, convention=ind.convention,
        deps=ind.deps, build=ind.build,
        render={**ind.render, "phantom": {"type": "line", "color": None}},
        sessioned=True, session_agg=ind.session_agg,
    )
    with pytest.raises(ValueError, match="phantom"):
        session_columns(_intraday(), broken, broken.params)
