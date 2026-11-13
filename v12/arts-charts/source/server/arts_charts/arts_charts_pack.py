# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Art's Charts' study pack (spec 2026-11-04 S7): the 19 studies only Art's Charts has (eight of
them read a second ticker), written with openbq_ta's @study decorator. Art's Charts installs this
file into the shared studies folder (TA_STUDIES_DIR), so live-grid runs them too; it imports
nothing but the engine, Polars and the standard library."""
import math
from datetime import timezone

import polars as pl

from openbq_ta.exprs import Base, price_col
from openbq_ta.studies import study


# --- Hull moving average ----------------------------------------------------


def _wma_expr(expr: pl.Expr, length: int) -> pl.Expr:
    # rolling_mean(weights=...) panics on any null in the array (not just the
    # window) as of polars 1.44 -- fine for a raw price column, not for a
    # nested WMA-of-WMA input that is null through its own warmup. Fill nulls
    # so it doesn't panic, then null the result wherever the window itself
    # wasn't fully covered by real values -- identical output to a direct
    # weighted rolling_mean whenever the input has no nulls.
    weights = [float(i) for i in range(1, length + 1)]
    weighted = expr.fill_null(0.0).rolling_mean(length, weights=weights)
    enough = expr.is_not_null().cast(pl.Int32).rolling_sum(length) == length
    return pl.when(enough).then(weighted).otherwise(None)


@study(
    name="hma", label="Hull Moving Average", params={"period": 9},
    colors={"hma": "#56b6c2"}, pane="price", price_basis="adjusted",
    group="Moving averages", full="Hull moving average",
    desc="Halves WMA lag: WMA of (2·WMA(n/2) − WMA(n)) over √n bars.",
    param_labels={"period": 'Length'},
    description="Combines two weighted moving averages of different lengths to cancel out lag while keeping the line smooth, so it tracks price closely without the choppiness of a plain fast average. A turn in its slope is read as an early trend-change signal.",
    wiki=None, windows=("period",),
    convention=(
        "WMA(2*WMA(adj_close, round(n/2)) - WMA(adj_close, n), round(sqrt(n))). "
        "Both derived lengths are rounded to nearest, not truncated."
    ),
)
def hma(p):
    n = p["period"]
    price = pl.col(price_col("adjusted"))
    raw = 2 * _wma_expr(price, max(round(n / 2), 1)) - _wma_expr(price, n)
    return [_wma_expr(raw, max(round(math.sqrt(n)), 1)).alias("hma")]


# --- TRIX --------------------------------------------------------------------


@study(
    name="trix", label="TRIX", params={"period": 18},
    colors={"trix": "#c678dd"}, pane="own", price_basis="adjusted", guides=[0.0],
    group="Momentum", full="TRIX",
    desc="1-bar % change of a triple EMA.",
    param_labels={"period": 'Length'},
    description="The percentage rate of change of a price average that has been smoothed three times over, which strips out short-term noise more aggressively than a single moving average. Crossing above or below zero is read as a shift in the longer-term trend's direction.",
    wiki="https://www.investopedia.com/terms/t/trix.asp", windows=("period",),
    convention=(
        "1-bar percent change of a triple EMA(period) on adjusted close, "
        "alpha = 2/(period+1) matching the plain `ema` indicator. "
        "fill_nan(None): the EMA can be exactly zero, making the percent "
        "change 0/0."
    ),
)
def trix(p):
    alpha = 2 / (p["period"] + 1)  # matches the plain `ema` indicator
    smoothed = pl.col(price_col("adjusted"))
    for _ in range(3):
        smoothed = smoothed.ewm_mean(alpha=alpha, adjust=False, ignore_nulls=True)
    # A zero-price frame (a synthetic fixture, a delisted symbol) makes
    # pct_change divide 0/0 -> NaN. Unlike uo/chop/vortex there is no
    # zero-numerator or zero-denominator invariant to lean on here -- any
    # prior EMA can be exactly zero -- so this is a plain fill_nan, not a
    # guarded expression.
    return [(100 * smoothed.pct_change(1)).fill_nan(None).alias("trix")]


# --- Supertrend: a recurrence ------------------------------------------------


def _supertrend(df: pl.DataFrame, params: dict) -> dict[str, list[float | None]]:
    """ATR-banded trailing stop that flips side when close crosses the band.

    Reads `tr:raw:0`, which the vectorised pass has already materialised, and
    smooths it with Wilder's alpha = 1/n here rather than declaring an ewm
    Base -- the Base vocabulary keys on a column name, and true range is
    keyed `tr:raw:0` regardless of period.
    """
    period = int(params["period"])
    multiplier = float(params["multiplier"])
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    closes = df["close"].to_list()
    count = len(closes)
    if not count:
        return {"supertrend": [], "st_direction": []}

    true_range = df["tr:raw:0"].to_list()
    atr: list[float | None] = [None] * count
    running = None
    for i, value in enumerate(true_range):
        if value is None:
            continue
        running = value if running is None else running + (value - running) / period
        atr[i] = running

    line: list[float | None] = [None] * count
    direction: list[float | None] = [None] * count
    upper = lower = None
    way = 1.0
    # Bar 0 has no prior close to test the band against (the same "no prior
    # state" warmup SAR uses) -- tr:raw:0 is non-null at bar 0 (it degrades to
    # high - low), so atr[0] is set and this loop must skip it explicitly
    # rather than rely on `atr[i] is None` to do it.
    for i in range(1, count):
        if atr[i] is None:
            continue
        middle = (highs[i] + lows[i]) / 2
        basic_upper = middle + multiplier * atr[i]
        basic_lower = middle - multiplier * atr[i]
        # A band only ever tightens, until price closes through it.
        upper = (basic_upper if upper is None or basic_upper < upper
                 or closes[i - 1] > upper else upper)
        lower = (basic_lower if lower is None or basic_lower > lower
                 or closes[i - 1] < lower else lower)
        if way == 1.0 and closes[i] < lower:
            way = -1.0
        elif way == -1.0 and closes[i] > upper:
            way = 1.0
        line[i] = lower if way == 1.0 else upper
        direction[i] = way
    return {"supertrend": line, "st_direction": direction}


# st_direction is returned too but is deliberately NOT in colors: it is internal state, not a
# plotted study, and a width-0 line would still ship an invisible series to the client.
study(
    name="supertrend", label="Supertrend", params={"period": 10, "multiplier": 3.0},
    colors={"supertrend": "#98c379"}, pane="price", price_basis="raw",
    group="Trend", full="Supertrend",
    desc="ATR-banded trailing stop; flips on close-through.",
    param_labels={"period": 'ATR length', "multiplier": 'ATR multiplier'},
    param_steps={"multiplier": 0.5},
    description="A single trailing line set a multiple of average true range away from price, holding steady on one side until price closes through it. A flip in which side of price the line sits on is read as a change in trend direction.",
    wiki="https://www.investopedia.com/supertrend-indicator-7976167", windows=("period",),
    convention=(
        "Wilder ATR(period)-banded trailing stop on raw OHLC. The band only "
        "tightens until close crosses it, then the side flips. Path-dependent "
        "like Parabolic SAR, so it runs in the iterative pass."
    ),
    deps=lambda p: [Base("tr", "raw", 0)],
    iterate=_supertrend,
)


# --- Awesome oscillator -----------------------------------------------------


@study(name="ao", label="Awesome Oscillator", params={}, pane="own", price_basis="raw",
       guides=[0.0], colors={"ao": "#98c379"}, render={"ao": {"type": "bar"}},
       group="Momentum", full="Awesome Oscillator", desc="SMA(HL2,5) − SMA(HL2,34).",
       param_labels={},
       description="The difference between a short and a long simple average of the midpoint of each bar's high and low, plotted as a histogram around zero. Bars switching from below to above zero, or a change in the bars' color, are read as a shift in short-term momentum.",
       wiki=None,
       convention="SMA(HL2, 5) - SMA(HL2, 34) on raw high/low. Fixed periods (Bill Williams).")
def ao(p):
    mid = (pl.col("high") + pl.col("low")) / 2
    return [(mid.rolling_mean(5) - mid.rolling_mean(34)).alias("ao")]


# --- Money flow index -------------------------------------------------------


@study(
    name="mfi", label="Money Flow Index", params={"period": 14},
    colors={"mfi": "#d19a66"},
    group="Volume", full="Money Flow Index",
    desc="Volume-weighted RSI.",
    param_labels={"period": 'Length'},
    description="Combines price and volume into a single 0-100 oscillator, similar to RSI but weighting each bar's contribution by how much volume traded on it. High readings are read as overbought and low readings as oversold, with more weight given to heavy-volume moves.",
    wiki="https://www.investopedia.com/terms/m/mfi.asp",
    windows=("period",), pane="own",
    price_basis="raw", guides=[20.0, 80.0],
    convention=(
        "Typical price (H+L+C)/3, raw money flow = TP*volume, bucketed by the "
        "sign of TP.diff() and summed over `period` bars. A window with no "
        "typical-price movement is null, not 0 and not NaN."
    ),
)
def mfi(p):
    n = p["period"]
    typical = (pl.col("high") + pl.col("low") + pl.col("close")) / 3
    flow = typical * pl.col("volume")
    moved = typical.diff()
    positive = pl.when(moved > 0).then(flow).otherwise(0.0).rolling_sum(n)
    negative = pl.when(moved < 0).then(flow).otherwise(0.0).rolling_sum(n)
    total = positive + negative
    # A flat window has no flow in either bucket: 0/0. Null it here rather
    # than letting a NaN reach the response boundary.
    return [pl.when(total > 0).then(100 * positive / total)
              .otherwise(None).alias("mfi")]


# --- Chaikin money flow -----------------------------------------------------


@study(
    name="cmf", label="Chaikin Money Flow", params={"period": 20},
    colors={"cmf": "#61afef"},
    group="Volume", full="Chaikin Money Flow",
    desc="Money-flow volume ÷ volume over N bars.",
    param_labels={"period": 'Length'},
    description="Measures whether volume over the lookback window is concentrated on bars that closed near their high or near their low, summed and scaled by total volume. Sustained positive readings are read as accumulation and sustained negative readings as distribution.",
    wiki=None,
    windows=("period",), pane="own",
    price_basis="raw", guides=[0.0],
    convention=(
        "Sum of money-flow multiplier * volume over `period` bars, divided by "
        "summed volume. Flat bars (high == low) contribute 0, not NaN."
    ),
)
def cmf(p):
    n = p["period"]
    span = pl.col("high") - pl.col("low")
    # A flat bar (high == low) contributes zero flow. Dividing would be 0/0
    # and would poison every window it touches.
    multiplier = pl.when(span > 0).then(
        (2 * pl.col("close") - pl.col("high") - pl.col("low")) / span
    ).otherwise(0.0)
    volume_sum = pl.col("volume").rolling_sum(n)
    return [pl.when(volume_sum > 0)
              .then((multiplier * pl.col("volume")).rolling_sum(n) / volume_sum)
              .otherwise(None).alias("cmf")]


# --- Ultimate oscillator ----------------------------------------------------


@study(
    name="uo", label="Ultimate Oscillator", colors={"uo": "#e5c07b"},
    group="Momentum", full="Ultimate Oscillator",
    desc="Weighted BP/TR blend across 3 windows.",
    param_labels={"fast": 'Fast window', "mid": 'Mid window', "slow": 'Slow window'},
    description="Blends buying pressure measured over three different lookback lengths into one 0-100 reading, weighting the shortest window most heavily so it reacts quickly while still reflecting the longer-term picture. High readings are read as overbought and low readings as oversold.",
    wiki="https://www.investopedia.com/terms/u/ultimateoscillator.asp",
    params={"fast": 7, "mid": 14, "slow": 28},
    windows=("fast", "mid", "slow"), pane="own",
    price_basis="raw", guides=[30.0, 70.0],
    convention=(
        "Weighted blend of buying-pressure / true-range sum-ratios at three "
        "windows, weights 4:2:1, divisor 7. BP = close - min(low, prior close). "
        "Ratio of sums, not mean of ratios. fill_nan(None) suffices here: "
        "TR_t == 0 forces close_t == close_{t-1}, which forces buying_t == 0 "
        "too, so a zero-TR window is always 0/0 (NaN), never x/0."
    ),
    deps=lambda p: [Base("tr", "raw", 0)],
)
def uo(p):
    buying = pl.col("close") - pl.min_horizontal(pl.col("low"), pl.col("close").shift(1))
    true_range = pl.col("tr:raw:0")

    def ratio(n: int) -> pl.Expr:
        # Ratio of sums, NOT mean of ratios: the two agree only when true
        # range is constant, and it never is.
        return buying.rolling_sum(n) / true_range.rolling_sum(n)

    blended = 100 * (4 * ratio(p["fast"]) + 2 * ratio(p["mid"]) + ratio(p["slow"])) / 7
    return [blended.fill_nan(None).alias("uo")]


# --- Vortex indicator -------------------------------------------------------


@study(
    name="vortex", label="Vortex Indicator", params={"period": 14},
    colors={"vi_plus": "#98c379", "vi_minus": "#e06c75"},
    group="Trend strength", full="Vortex Indicator",
    desc="VI+/VI− crossover marks trend starts.",
    param_labels={"period": 'Length'},
    description="Compares how far price has moved up against the prior bar's low to how far it has moved down against the prior bar's high, plotted as two lines. Whichever line crosses above the other is read as the currently dominant trend direction.",
    wiki="https://www.investopedia.com/terms/v/vortex-indicator-vi.asp",
    windows=("period",), pane="own",
    price_basis="raw",
    convention=(
        "VM+ = |high - prior low|, VM- = |low - prior high|, each summed over "
        "`period` bars and divided by summed true range. The tr base is "
        "period-independent, keyed tr:raw:0."
    ),
    deps=lambda p: [Base("tr", "raw", 0)],
)
def vortex(p):
    n = p["period"]
    total = pl.col("tr:raw:0").rolling_sum(n)
    up = (pl.col("high") - pl.col("low").shift(1)).abs().rolling_sum(n)
    down = (pl.col("low") - pl.col("high").shift(1)).abs().rolling_sum(n)
    # up/down read the PRIOR bar's low/high, not the prior close, so a window
    # with zero summed true range can still have a nonzero numerator here --
    # unlike uo and chop, x/0 with x != 0 is +inf, which fill_nan cannot
    # catch. Guard the denominator directly, like chop does.
    return [pl.when(total > 0).then(up / total).otherwise(None).alias("vi_plus"),
            pl.when(total > 0).then(down / total).otherwise(None).alias("vi_minus")]


# --- Choppiness index -------------------------------------------------------


@study(
    name="chop", label="Choppiness Index", params={"period": 14},
    colors={"chop": "#d19a66"},
    group="Trend strength", full="Choppiness Index",
    desc="Range vs trend gauge, not directional.",
    param_labels={"period": 'Length'},
    description="Measures whether price is trending or moving sideways by comparing the sum of daily ranges to the overall range of the lookback window, scaled between zero and one hundred. A high reading is read as a choppy, non-trending market, while a low reading suggests a sustained directional move.",
    wiki=None,
    windows=("period",), pane="own",
    price_basis="raw", guides=[38.2, 61.8],
    convention=(
        "100 * log10(sum(TR, n) / (highest high - lowest low)) / log10(n) on "
        "raw OHLC. A range/trendiness gauge, not a directional one -- high is "
        "choppy, low is trending. span == 0 forces every in-window bar to the "
        "same price, so span > 0 implies the summed true range is too -- the "
        "`span > 0` guard fully closes the divide-by-zero case."
    ),
    deps=lambda p: [Base("tr", "raw", 0), Base("max", "high", p["period"]),
                    Base("min", "low", p["period"])],
)
def chop(p):
    n = p["period"]
    span = pl.col(f"max:high:{n}") - pl.col(f"min:low:{n}")
    ratio = pl.col("tr:raw:0").rolling_sum(n) / span
    return [pl.when(span > 0)
              .then(100 * ratio.log(base=10) / math.log10(n))
              .otherwise(None).alias("chop")]


# --- Ichimoku cloud ---------------------------------------------------------


def _midpoint(period: int) -> pl.Expr:
    return (pl.col(f"max:high:{period}") + pl.col(f"min:low:{period}")) / 2


# `render` is static, shared by every request for this study, so these offsets cannot read the
# resolved `displacement` param -- they are pinned to its default. Fixing that needs the render
# to become a callable of params; nobody has asked for a non-default displacement yet, so it
# stays a known gap.
@study(
    name="ichimoku", label="Ichimoku Cloud",
    group="Trend", full="Ichimoku Cloud",
    desc="Displaced cloud — rendered server-side in this build.",
    param_labels={"conversion": 'Conversion', "base": 'Base', "span_b": 'Span B', "displacement": 'Displacement'},
    description="A cluster of lines built from rolling highs and lows at three different lengths, plus the current close and a shaded cloud between two of the lines. Price relative to the cloud is read as the trend's direction, and the cloud's thickness is read as the strength of support or resistance ahead.",
    wiki="https://www.investopedia.com/terms/i/ichimoku-cloud.asp",
    params={"conversion": 9, "base": 26, "span_b": 52, "displacement": 26},
    windows=("conversion", "base", "span_b"),
    pane="price", price_basis="raw",
    convention=(
        "Tenkan/Kijun/Senkou B from rolling high-low midpoints on raw OHLC. "
        "Values sit at the row they are COMPUTED from; the leading spans and "
        "Chikou are displaced via render['time_offset'], never by shifting "
        "the column. That offset is fixed at the default `displacement` "
        "(26) -- a non-default `displacement` moves the midpoint windows but "
        "plots the result at the same default offset (see render below)."
    ),
    deps=lambda p: [
        Base("max", "high", p["conversion"]), Base("min", "low", p["conversion"]),
        Base("max", "high", p["base"]), Base("min", "low", p["base"]),
        Base("max", "high", p["span_b"]), Base("min", "low", p["span_b"]),
    ],
    colors={"ichi_conversion": "#4c9be8", "ichi_base": "#e06c75", "ichi_span_a": "#8ed081",
            "ichi_span_b": "#e5c07b", "ichi_chikou": "#9aa0a6"},
    render={"ichi_span_a": {"time_offset": 26}, "ichi_span_b": {"time_offset": 26},
            "ichi_chikou": {"time_offset": -26}},
)
def ichimoku(p):
    conversion = _midpoint(p["conversion"])
    base = _midpoint(p["base"])
    # No .shift() anywhere: the displacement is a plotting property, declared
    # per series as render["time_offset"] and applied by panes.shift_times.
    return [
        conversion.alias("ichi_conversion"),
        base.alias("ichi_base"),
        ((conversion + base) / 2).alias("ichi_span_a"),
        _midpoint(p["span_b"]).alias("ichi_span_b"),
        pl.col("close").alias("ichi_chikou"),
    ]


# --- Pivot points (classic / floor) -----------------------------------------


def _pivots_session_agg(p: dict) -> dict:
    return {"H": pl.col("high").max(), "L": pl.col("low").min(),
            "C": pl.col("close").last()}


@study(
    name="pivots_standard", label="Pivot Points Standard",
    group="Session levels", full="Pivot Points Standard",
    desc="Prior-session floor pivots, held flat — server-side.",
    param_labels={"anchor": 'Session cadence', "session_shift": 'Sessions back'},
    description="Projects support and resistance levels for the current session from the prior session's high, low, and close, drawn as flat lines. Price approaching one of these levels is read as a likely area where the move may pause or reverse.",
    wiki="https://www.investopedia.com/terms/p/pivotpoint.asp",
    params={"anchor": "1d", "session_shift": 1}, pane="price", price_basis="raw",
    convention=(
        "Classic floor pivots from the PRIOR session's high/low/close, held "
        "flat across the current session. group_by_dynamic(every=anchor) -> "
        "shift(session_shift) -> join_asof(backward). The first session has no "
        "prior and is null, not zero."
    ),
    session_agg=_pivots_session_agg,
    colors={name: "#9aa0a6" for name in ("PP", "R1", "S1", "R2", "S2", "R3", "S3")},
)
def pivots_standard(p):
    # Runs against the collapsed, already-shifted session frame, so H/L/C here
    # are the PRIOR session's.
    pivot = (pl.col("H") + pl.col("L") + pl.col("C")) / 3
    return [
        pivot.alias("PP"),
        (2 * pivot - pl.col("L")).alias("R1"),
        (2 * pivot - pl.col("H")).alias("S1"),
        (pivot + (pl.col("H") - pl.col("L"))).alias("R2"),
        (pivot - (pl.col("H") - pl.col("L"))).alias("S2"),
        (pl.col("H") + 2 * (pivot - pl.col("L"))).alias("R3"),
        (pl.col("L") - 2 * (pl.col("H") - pivot)).alias("S3"),
    ]


# --- Cross-symbol studies (spec 2026-11-13 cross-symbol §2) ------------------
# Each reads a second ticker named by `vs`. The engine runs it on the bars both tickers share,
# the other's columns as vs_open ... vs_adj_close (openbq_ta compute, tickers=), and joins it back
# by date: a date either side lacks is a gap with a note. Returns are 1-bar percent changes.

_A = pl.col("adj_close")
_B = pl.col("vs_adj_close")


def _returns(price: pl.Expr) -> pl.Expr:
    return 100 * price.pct_change()


def _zscore(x: pl.Expr, n: int) -> pl.Expr:
    return (x - x.rolling_mean(n)) / x.rolling_std(n)


@study(
    name="ratio", label="RATIO", params={"vs": None}, colors={"ratio": "#e5c07b"},
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Price ratio",
    desc="Adjusted close ÷ the other ticker's adjusted close.",
    param_labels={"vs": "Versus"}, tickers=("vs",), wiki=None,
    description="Divides this ticker's price by another's on every date both trade, so a rising line means this one is outperforming the other and a falling line means it is lagging behind.",
    convention="adj_close / vs_adj_close on the dates both tickers have; a date either lacks is a gap.",
)
def ratio(p):
    return [(_A / _B).alias("ratio")]


@study(
    name="spread", label="SPREAD", params={"vs": None, "multiple": 1.0},
    colors={"spread": "#e5c07b"}, guides=(0,),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Price spread",
    desc="Adjusted close − multiple × the other ticker's adjusted close.",
    param_labels={"vs": "Versus", "multiple": "Multiple"}, param_steps={"multiple": 0.1},
    tickers=("vs",), wiki=None,
    description="Subtracts a multiple of another ticker's price from this one's on every shared date, the classic pairs spread; it crosses zero where the two stand in the chosen balance.",
    convention="adj_close - multiple * vs_adj_close on shared dates.",
)
def spread(p):
    return [(_A - p["multiple"] * _B).alias("spread")]


@study(
    name="corr", label="CORR", params={"vs": None, "period": 60}, colors={"corr": "#c678dd"},
    guides=(-1, 0, 1), windows=("period",),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Rolling correlation",
    desc="Correlation of the two tickers' daily returns over N shared bars.",
    param_labels={"vs": "Versus", "period": "Length"}, tickers=("vs",),
    wiki="https://www.investopedia.com/terms/c/correlation.asp",
    description="Measures how closely the two tickers' bar-to-bar returns move together over the window, from minus one (opposite) through zero (unrelated) to one (in lockstep).",
    convention="Pearson correlation of 100*pct_change(adj_close) and 100*pct_change(vs_adj_close) over `period` shared bars.",
)
def corr(p):
    return [pl.rolling_corr(_returns(_A), _returns(_B), window_size=p["period"])
            .fill_nan(None).alias("corr")]


@study(
    name="beta", label="BETA", params={"vs": None, "period": 60}, colors={"beta": "#c678dd"},
    guides=(1,), windows=("period",),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Rolling beta",
    desc="Covariance of the returns ÷ variance of the other's returns, over N shared bars.",
    param_labels={"vs": "Versus", "period": "Length"}, tickers=("vs",),
    wiki="https://www.investopedia.com/terms/b/beta.asp",
    description="Estimates how far this ticker tends to move for each one percent the other moves over the window; one means it moves with it, above one more, below one less.",
    convention="rolling sample cov(r, r_vs) / rolling sample var(r_vs) over `period` shared bars, r = 100*pct_change(adj_close).",
)
def beta(p):
    n = p["period"]
    return [(pl.rolling_cov(_returns(_A), _returns(_B), window_size=n)
             / _returns(_B).rolling_var(n)).fill_nan(None).alias("beta")]


@study(
    name="retdiff", label="RETDIFF", params={"vs": None}, colors={"retdiff": "#98c379"},
    guides=(0,), render={"retdiff": {"type": "bar"}},
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Return difference",
    desc="This ticker's 1-bar return minus the other's, as a histogram.",
    param_labels={"vs": "Versus"}, tickers=("vs",), wiki=None,
    description="Shows, bar by bar, how much more or less this ticker returned than the other one, so runs of bars above zero mark stretches where it kept outperforming.",
    convention="100*pct_change(adj_close) - 100*pct_change(vs_adj_close) on shared bars.",
)
def retdiff(p):
    return [(_returns(_A) - _returns(_B)).alias("retdiff")]


@study(
    name="relret", label="RELRET", params={"vs": None, "anchor": None},
    colors={"relret": "#56b6c2"}, guides=(0,), times=("anchor",),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Relative return",
    desc="Return since the anchor relative to the other ticker's; no anchor is the first shared bar.",
    param_labels={"vs": "Versus", "anchor": "Anchor"}, tickers=("vs",), wiki=None,
    description="Rebases both tickers to the anchor date and shows how far this one has gained or lost against the other since then, as a fraction where 0.05 means five percent ahead.",
    convention="(adj_close / adj_close@anchor) / (vs_adj_close / vs_adj_close@anchor) - 1; null before the anchor.",
)
def relret(p):
    anchor = p.get("anchor")   # a UTC datetime (times=("anchor",)) or None: the first shared bar
    at = (pl.col("date").is_not_null() if anchor is None
          else pl.col("date").cast(pl.Datetime)
          >= pl.lit(anchor.astimezone(timezone.utc).replace(tzinfo=None)))
    return [pl.when(at).then((_A / _A.filter(at).first()) / (_B / _B.filter(at).first()) - 1)
            .alias("relret")]


@study(
    name="returns", label="RETURNS", params={"vs": None},
    colors={"r": "#61afef", "r_vs": "#e06c75"}, guides=(0,),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Daily returns",
    desc="Both tickers' 1-bar percent returns, as two lines.",
    param_labels={"vs": "Versus"}, tickers=("vs",), wiki=None,
    description="Draws each ticker's bar-to-bar percent return on the dates both trade, so a reader can see side by side which one moved more on any given day.",
    convention="r = 100*pct_change(adj_close), r_vs = 100*pct_change(vs_adj_close) on shared bars.",
)
def returns(p):
    return [_returns(_A).alias("r"), _returns(_B).alias("r_vs")]


@study(
    name="zscore", label="ZSCORE", params={"vs": None, "of": "ratio", "period": 60, "multiple": 1.0},
    colors={"zscore": "#d19a66"}, guides=(-2, 0, 2), windows=("period",),
    pane="own", price_basis="adjusted", group="Cross-symbol", full="Z-score of ratio or spread",
    desc="How many standard deviations the ratio or spread sits from its N-bar mean.",
    param_labels={"vs": "Versus", "of": "Of series", "period": "Length", "multiple": "Multiple"},
    param_steps={"multiple": 0.1}, tickers=("vs",),
    wiki="https://www.investopedia.com/terms/z/zscore.asp",
    description="Standardises the price ratio or spread against its own recent mean and spread, so readings beyond two in either direction flag an unusually stretched relationship between the pair.",
    convention="(x - rolling_mean(x, period)) / rolling_std(x, period, ddof=1), x = ratio or adj_close - multiple * vs_adj_close.",
)
def zscore(p):
    if p["of"] not in ("ratio", "spread"):
        raise ValueError(f"of must be ratio or spread, got {p['of']!r}")
    x = _A / _B if p["of"] == "ratio" else _A - p["multiple"] * _B
    return [_zscore(x, p["period"]).fill_nan(None).alias("zscore")]
