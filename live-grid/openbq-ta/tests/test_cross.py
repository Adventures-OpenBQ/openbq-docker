# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""A study that reads a second ticker (spec 2026-11-13 cross-symbol §1): `tickers=`, the
shared-bar join, and its notes. AAPL has no bar on the 4th, MSFT none on the 7th."""
import statistics
from datetime import datetime, timedelta

import polars as pl
import pytest

from openbq_ta import studies
from openbq_ta.compute import compute
from openbq_ta.registry import StudyError, get, resolve

DAYS = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(10)]
AAPL = [10, 11, 12, None, 12.5, 13, 14, 13.5, 15, 16]
MSFT = [20, 21, 21.5, 22, 23, 22.5, None, 24, 25, 24.5]
# The eight dates both have, in order.
SA = [10, 11, 12, 12.5, 13, 13.5, 15, 16]
SM = [20, 21, 21.5, 23, 22.5, 24, 25, 24.5]
RA = [None, *(SA[i] / SA[i - 1] - 1 for i in range(1, 8))]
RM = [None, *(SM[i] / SM[i - 1] - 1 for i in range(1, 8))]


def bars(closes):
    rows = [(d, float(c)) for d, c in zip(DAYS, closes) if c is not None]
    price = pl.Series([c for _, c in rows], dtype=pl.Float64)
    return pl.DataFrame({"date": pl.Series([d for d, _ in rows], dtype=pl.Datetime("us")),
                         "open": price, "high": price, "low": price, "close": price,
                         "adj_close": price, "volume": pl.Series([1.0] * len(rows))})


def on_aapl(shared):
    """Shared-date values on AAPL's nine rows: its 7th, which MSFT lacks, is a gap."""
    return [*shared[:5], None, *shared[5:]]


@pytest.fixture(autouse=True)
def pair():
    @studies.study(name="t_ratio", label="T_RATIO", params={"vs": None}, colors={"r": None},
                   tickers=("vs",))
    def t_ratio(p):
        return [(pl.col("adj_close") / pl.col("vs_adj_close")).alias("r")]

    @studies.study(name="t_corr", label="T_CORR", params={"vs": None, "period": 3},
                   colors={"c": None}, tickers=("vs",), windows=("period",))
    def t_corr(p):
        r, rv = pl.col("adj_close").pct_change(), pl.col("vs_adj_close").pct_change()
        return [pl.rolling_corr(r, rv, window_size=p["period"]).alias("c")]
    yield
    studies.unload("<runtime>")


def run(*reqs, others=None, notes=None):
    return compute(bars(AAPL), list(reqs), notes=notes, symbol="AAPL",
                   others={"MSFT": bars(MSFT)} if others is None else others)


def test_the_registry_carries_tickers():
    assert get("t_ratio").tickers == ("vs",)
    assert get("sma").tickers == ()


@pytest.mark.parametrize("kwargs, reason", [
    ({"params": {"vs": None}, "tickers": ("other",)}, r"tickers \['other'\] are not parameters"),
    ({"params": {"vs": None, "vs2": None}, "tickers": ("vs", "vs2")}, "reads one other ticker"),
    ({"params": {"vs": None}, "tickers": ("vs",), "iterate": lambda f, p: {"x": []}}, "vectorised"),
])
def test_a_ticker_parameter_is_one_parameter_of_a_vectorised_study(kwargs, reason):
    with pytest.raises(StudyError, match=reason):
        studies.study(name="t_bad", label="T_BAD", colors={"x": None}, **kwargs)


def test_the_shared_bar_join_leaves_a_gap_where_either_side_lacks_a_bar():
    out = run(resolve("t_ratio", vs="MSFT"), notes=[])
    assert out["date"].to_list() == bars(AAPL)["date"].to_list()   # the card's rows, row for row
    assert out["r|vs=MSFT"].to_list() == pytest.approx(on_aapl([a / m for a, m in zip(SA, SM)]))
    assert not [c for c in out.columns if c.startswith("vs_")]


def test_a_planted_gap_does_not_shift_a_three_bar_correlation():
    out = run(resolve("t_corr", vs="MSFT"), notes=[])
    shared = [None if i < 3 else statistics.correlation(RA[i - 2:i + 1], RM[i - 2:i + 1])
              for i in range(8)]
    assert out["c|period=3,vs=MSFT"].to_list() == pytest.approx(on_aapl(shared))


def test_the_note_counts_each_side_over_the_union_of_dates():
    notes = []
    run(resolve("t_ratio", vs="MSFT"), notes=notes)
    assert [m for _, m in notes] == ["vs MSFT: 1 of 10 dates has no MSFT bar, 1 has no AAPL bar"]


def test_the_note_names_only_the_side_that_lacks_dates_and_none_when_nothing_is_missing():
    notes = []
    run(resolve("t_ratio", vs="MSFT"), others={"MSFT": bars([20.0] * 10)}, notes=notes)
    assert [m for _, m in notes] == ["vs MSFT: 1 of 10 dates has no AAPL bar"]
    notes.clear()
    compute(bars([10.0] * 10), [resolve("t_ratio", vs="MSFT")],
            others={"MSFT": bars([20.0] * 10)}, notes=notes, symbol="AAPL")
    assert notes == []


def test_what_a_ticker_study_cannot_compute_is_a_note_and_the_rest_computes():
    notes = []
    out = run(resolve("t_ratio"), resolve("t_ratio", vs="NVDA"),
              resolve("t_corr", None, {"period": "bd"}, vs="MSFT", period=3),
              resolve("sma", period=3), notes=notes)
    assert [m for _, m in notes] == ["T_RATIO needs a second ticker", "no bars for NVDA",
                                     "bd windows are not available on cross-symbol studies"]
    assert out["sma|period=3"].null_count() == 2


def test_without_a_notes_list_a_refusal_raises():
    with pytest.raises(StudyError, match="T_RATIO needs a second ticker"):
        compute(bars(AAPL), [resolve("t_ratio")])


def test_exprs_of_refuses_a_ticker_study():
    with pytest.raises(StudyError, match="second ticker"):
        studies.exprs_of("t_ratio", vs="MSFT")


def test_a_repeated_date_on_the_other_ticker_is_a_note_and_the_card_keeps_its_rows():
    notes = []
    dup = pl.concat([bars(MSFT), bars(MSFT).head(1)])   # MSFT's first date, twice
    out = run(resolve("t_ratio", vs="MSFT"), others={"MSFT": dup}, notes=notes)
    assert out.height == len(bars(AAPL))
    assert "r|vs=MSFT" not in out.columns
    assert [m for _, m in notes] == ["join keys did not fulfill 1:1 validation"]
