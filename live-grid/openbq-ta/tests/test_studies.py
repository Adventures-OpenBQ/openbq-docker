# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The @study decorator, the loader and the folder sync."""
import logging
import os
import textwrap

import polars as pl
import pytest

from openbq_ta import studies
from openbq_ta.compute import compute
from openbq_ta.registry import REGISTRY, StudyError, get, resolve
from tests.ta_helpers import fixture_frame

MID = '''
import polars as pl
from openbq_ta.studies import study

@study(name="mid_line", label="Mid {label}", params={"period": 5}, colors={"mid": "#fff"},
       pane="price", windows=("period",))
def mid(p):
    return [((pl.col("high") + pl.col("low")) / 2).rolling_mean(p["period"]).alias("mid")]
'''


@pytest.fixture(autouse=True)
def clean():
    yield
    for stem in list(studies.installed()):
        studies.unload(stem)
    studies._MTIMES.clear()


def write(directory, stem, text, mtime=None):
    path = directory / f"{stem}.py"
    path.write_text(text)
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))
    return path


def test_a_decorated_study_registers_and_computes(tmp_path):
    assert studies.load_file(write(tmp_path, "mid", MID.replace("{label}", "a"))) == ["mid_line"]
    out = compute(fixture_frame(), [resolve("mid_line")])
    assert out["mid|period=5"].null_count() == 4


def test_iterate_registers_a_path_dependent_study_and_returns_the_function():
    def run(frame, params):
        return {"count": [float(i) for i in range(frame.height)], "extra": [0.0] * frame.height}
    assert studies.study(name="t_count", label="Count", params={}, colors={"count": "#fff"},
                         iterate=run) is run
    ind = get("t_count")
    assert ind.iterative and ind.iterate is run and ind.build({}, {}) == []
    out = compute(fixture_frame(), [resolve("t_count")])
    assert out["count"][3] == 3.0 and "extra" in out.columns
    studies.unload("<runtime>")


def test_session_agg_adds_a_daily_anchor_and_runs_on_the_session_frame():
    @studies.study(name="t_prior_close", label="Prior close", params={"session_shift": 1},
                   colors={"prior": "#fff"}, session_agg=lambda p: {"C": pl.col("close").last()})
    def prior(p):
        return [pl.col("C").alias("prior")]
    ind = get("t_prior_close")
    assert ind.sessioned and ind.params == {"anchor": "1d", "session_shift": 1}
    studies.unload("<runtime>")


@pytest.mark.parametrize("kwargs, match", [
    ({"times": ("start",)}, "times"),
    ({"render": {"other": {"type": "bar"}}}, "render"),
    ({"iterate": lambda f, p: {}, "session_agg": lambda p: {}}, "iterate"),
])
def test_the_decorator_refuses_inconsistent_arguments(kwargs, match):
    with pytest.raises(StudyError, match=match):
        studies.study(name="t_bad", label="Bad", params={"period": 1}, colors={"x": "#fff"},
                      **kwargs)


def test_render_merges_per_output_keys_over_the_line():
    @studies.study(name="t_hist", label="Hist", params={}, colors={"h": "#123"},
                   render={"h": {"type": "bar"}})
    def hist(p):
        return [pl.col("close").alias("h")]
    assert get("t_hist").render == {"h": {"type": "bar", "color": "#123"}}
    studies.unload("<runtime>")


def test_the_decorator_refuses_to_shadow_a_built_in():
    with pytest.raises(StudyError, match="built-in"):
        studies.study(name="sma", label="x", params={}, colors={"sma": "#fff"})(
            lambda p: [pl.col("close").alias("sma")])


def test_load_dir_skips_a_broken_file_and_keeps_the_rest(tmp_path, caplog):
    write(tmp_path, "mid", MID.replace("{label}", "a"))
    write(tmp_path, "broken", "raise RuntimeError('nope')")
    with caplog.at_level(logging.WARNING):
        assert set(studies.load_dir(tmp_path)) == {"mid"}
    assert "broken.py" in caplog.text


def test_sync_dir_loads_new_files_reloads_changed_ones_and_forgets_deleted_ones(tmp_path):
    path = write(tmp_path, "mid", MID.replace("{label}", "a"), mtime=1_000_000_000)
    studies.sync_dir(tmp_path)
    assert get("mid_line").label == "Mid a"
    write(tmp_path, "mid", MID.replace("{label}", "b"), mtime=1_000_000_000)
    studies.sync_dir(tmp_path)
    assert get("mid_line").label == "Mid a"          # same mtime: not re-read
    write(tmp_path, "mid", MID.replace("{label}", "b"), mtime=2_000_000_000)
    studies.sync_dir(tmp_path)
    assert get("mid_line").label == "Mid b"
    path.unlink()
    studies.sync_dir(tmp_path)
    assert "mid_line" not in REGISTRY


def test_sync_dir_skips_a_broken_file_and_keeps_the_rest(tmp_path, caplog):
    write(tmp_path, "mid", MID.replace("{label}", "a"))
    write(tmp_path, "broken", "this is not python")
    with caplog.at_level(logging.WARNING):
        studies.sync_dir(tmp_path)
    assert "mid_line" in REGISTRY and "broken.py" in caplog.text


def test_a_file_naming_a_built_in_is_skipped(tmp_path):
    write(tmp_path, "shadow", MID.replace('name="mid_line"', 'name="rsi"'))
    studies.sync_dir(tmp_path)
    assert get("rsi").label == "RSI" and studies.installed() == {}


def test_a_staged_upload_is_never_loaded(tmp_path):
    (tmp_path / ".mid.py.upload").write_text(MID.replace("{label}", "a"))
    studies.sync_dir(tmp_path)
    assert "mid_line" not in REGISTRY


def test_sync_dir_with_no_directory_does_nothing():
    studies.sync_dir(None)
    assert studies.installed() == {}


NESTED = textwrap.dedent('''
    import polars as pl
    from openbq_ta.studies import deps_of, exprs_of, study

    # docs/custom-studies.md, "Advanced example": kept identical to the sheet.
    @study(
        name="rsi_of_sma",
        label="RSI of SMA",
        full="RSI of a moving average",
        group="Momentum",
        pane="own",
        params={"period": 20, "rsi": 14},
        windows=("period", "rsi"),
        guides=[30.0, 70.0],
        colors={"rsi_of_sma": "#e5c07b"},
        pens={"rsi_of_sma": "dashed"},
        desc="Wilder's RSI on an SMA of adjusted close.",
        deps=lambda p: deps_of("sma", period=p["period"]),
    )
    def rsi_of_sma(p):
        """Wilder's RSI, computed on an SMA of adjusted close instead of the close."""
        sma = exprs_of("sma", period=p["period"])["sma"]
        delta = sma.diff()
        gain = pl.when(delta > 0).then(delta).otherwise(0.0)
        loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
        wilder = {"alpha": 1 / p["rsi"], "adjust": False, "ignore_nulls": True}
        rs = gain.ewm_mean(**wilder) / loss.ewm_mean(**wilder)
        return [(100 - 100 / (1 + rs)).fill_nan(None).alias("rsi_of_sma")]
''')


def test_the_decorator_refuses_an_alias_the_colors_do_not_name():
    with pytest.raises(StudyError, match="produces"):
        studies.study(name="bad", label="x", params={}, colors={"good": None})(
            lambda p: [pl.col("close").alias("wrong")])
    assert "bad" not in REGISTRY


def test_the_decorator_refuses_a_window_that_is_not_a_parameter():
    with pytest.raises(StudyError, match="windows"):
        studies.study(name="bad", label="x", params={}, windows=("n",), colors={"bad": None})


@pytest.mark.parametrize("kwargs, match", [
    ({"pens": {"nope": "dashed"}}, "pens name outputs"),
    ({"pens": {"x": "wavy"}}, "pen 'wavy'"),
    ({"widths": {"nope": 2}}, "widths name outputs"),
    ({"widths": {"x": 5}}, "width 5"),
    ({"widths": {"x": 1.5}}, "width 1.5"),
    ({"fill_pattern": "plaid"}, "fill_pattern"),
    ({"fill_opacity": 0}, "fill_opacity"),
    ({"fill_opacity": 1.5}, "fill_opacity"),
])
def test_the_decorator_refuses_a_bad_pen_or_fill(kwargs, match):
    with pytest.raises(StudyError, match=match):
        studies.study(name="x", label="x", params={}, colors={"x": None}, **kwargs)
    assert "x" not in REGISTRY


def test_a_study_can_nest_another_studys_expressions_and_declare_its_deps(tmp_path):
    (tmp_path / "nested.py").write_text(NESTED)
    studies.load_file(tmp_path / "nested.py")
    frame = compute(fixture_frame(), [resolve("rsi_of_sma", period=5, rsi=3)])
    values = [v for v in frame["rsi_of_sma|period=5,rsi=3"].to_list() if v is not None]
    assert len(values) > 200 and all(0.0 <= v <= 100.0 for v in values)
    # The same thing by hand, so the nesting is the built-in's expression and not a lookalike.
    by_hand = compute(fixture_frame(), [resolve("sma", period=5)])["sma|period=5"]
    sma_col = frame.select(pl.col("adj_close").rolling_mean(5))[:, 0]
    assert by_hand.to_list() == sma_col.to_list()


def test_nesting_refuses_a_study_that_is_not_an_expression():
    with pytest.raises(StudyError, match="cannot be nested"):
        studies.exprs_of("sar")


def test_nesting_resolves_defaults_and_rejects_unknown_parameters():
    assert set(studies.exprs_of("bbands")) == {"bb_mid", "bb_up", "bb_lo"}
    assert [b.key for b in studies.deps_of("bbands", period=10)] == ["sma:adj_close:10", "std:adj_close:10"]
    with pytest.raises(ValueError, match="unknown parameter"):
        studies.exprs_of("sma", window=3)


def test_load_dir_with_no_directory_is_empty():
    assert studies.load_dir(None) == {} and studies.load_dir("/nonexistent") == {}


def test_sync_dir_skips_a_dangling_symlink_and_a_file_deleted_mid_sync(tmp_path, caplog, monkeypatch):
    write(tmp_path, "mid", MID.replace("{label}", "a"))
    (tmp_path / "dangling.py").symlink_to(tmp_path / "nowhere.py")
    with caplog.at_level(logging.WARNING):
        studies.sync_dir(tmp_path)
    assert "mid_line" in REGISTRY and "dangling.py" in caplog.text
    # A file that vanishes between the glob and the stat is skipped the same way.
    real_stat = type(tmp_path).stat

    def flaky(self, *a, **k):
        if self.name == "mid.py":
            raise FileNotFoundError(self.name)
        return real_stat(self, *a, **k)
    monkeypatch.setattr(type(tmp_path), "stat", flaky)
    studies.sync_dir(tmp_path)
    assert "mid_line" not in REGISTRY
