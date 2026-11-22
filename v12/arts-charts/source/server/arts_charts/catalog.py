# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The studies picker's catalog (studies addendum §3): every field a picker or an editor
needs, none of the compute callables.

The engine (openbq_ta) carries the facts; the picker text for its built-ins -- long names,
one-line and long descriptions, links, parameter labels and spinner steps -- is Art's
Charts' own and lives here in PICKER. A decorated study (the pack, an operator's file)
carries its own picker text through the decorator.
"""
from __future__ import annotations

from openbq_ta.registry import REGISTRY, catalog_entry

PICKER: dict[str, dict] = {'sma': {'group': 'Moving averages',
         'full': 'Simple moving average',
         'desc': 'Arithmetic mean of adjusted close over N bars.',
         'description': 'Averages price over a fixed number of bars, smoothing out day-to-day '
                        'noise so the underlying trend stands out. Price crossing above or below '
                        'the line is often read as a shift in trend direction.',
         'wiki': 'https://www.investopedia.com/terms/s/sma.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'ema': {'group': 'Moving averages',
         'full': 'Exponential moving average',
         'desc': 'Weights recent bars most heavily; α = 2/(N+1).',
         'description': 'Averages price over a lookback window like a simple moving average, but '
                        'weights recent bars more heavily so it turns with price faster. Traders '
                        'read it the same way as an SMA, as a trend line, but it reacts sooner to '
                        'new moves.',
         'wiki': 'https://www.investopedia.com/terms/e/ema.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'rsi': {'group': 'Momentum',
         'full': 'Relative Strength Index',
         'desc': 'Wilder smoothed gain/loss ratio, 0–100.',
         'description': 'Compares the size of recent gains to recent losses on a 0-100 scale to '
                        'gauge whether a security has moved too far too fast. Readings above '
                        'roughly 70 are read as overbought and below 30 as oversold, though strong '
                        'trends can hold at extremes for a while.',
         'wiki': 'https://www.investopedia.com/terms/r/rsi.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'bbands': {'group': 'Bands & channels',
            'full': 'Bollinger Bands',
            'desc': 'Mid = SMA(N); bands = mid ± k · population σ.',
            'description': 'A moving average with two bands plotted a multiple of standard '
                           'deviation above and below it, so the band width expands and contracts '
                           'with volatility. Price pressing against or beyond a band is read as a '
                           'stretched, possibly overextended move relative to its recent range.',
            'wiki': 'https://www.investopedia.com/terms/b/bollingerbands.asp',
            'param_labels': {'period': 'Length', 'k': 'StdDev multiplier'},
            'param_steps': {'k': 0.5}},
 'atr': {'group': 'Volatility',
         'full': 'Average True Range',
         'desc': 'Wilder true-range mean, raw OHLC.',
         'description': "Averages the true range, the largest of the day's own range and any gap "
                        'from the prior close, to give a single measure of how much a security '
                        'typically moves per bar. It is read as a gauge of volatility, useful for '
                        'sizing stops or targets rather than for direction.',
         'wiki': 'https://www.investopedia.com/terms/a/atr.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'wma': {'group': 'Moving averages',
         'full': 'Weighted moving average',
         'desc': 'Linear weighting — newest bar counts N×, oldest 1×.',
         'description': 'Weights each bar in the lookback window in proportion to how recent it '
                        'is, so the most recent price counts several times as much as the oldest. '
                        'It sits between the SMA and EMA in responsiveness and is read the same '
                        'way, as a trend line.',
         'wiki': 'https://www.investopedia.com/ask/answers/071414/whats-difference-between-moving-average-and-weighted-moving-average.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'keltner': {'group': 'Bands & channels',
             'full': 'Keltner Channels',
             'desc': 'EMA ± mult · Wilder ATR, on raw OHLC range.',
             'description': 'An average price line with bands set a multiple of average true range '
                            'above and below it, so the channel width tracks volatility directly '
                            'instead of standard deviation. Price breaking outside the channel is '
                            'often read as the start of a stronger directional move.',
             'wiki': 'https://www.investopedia.com/terms/k/keltnerchannel.asp',
             'param_labels': {'period': 'EMA length',
                              'mult': 'ATR multiplier',
                              'atr_period': 'ATR length'},
             'param_steps': {'mult': 0.5}},
 'donchian': {'group': 'Bands & channels',
              'full': 'Price Channels',
              'desc': 'Upper = N-bar highest high, lower = lowest low.',
              'description': 'Plots the highest high and lowest low over the lookback window as a '
                             'channel, with the midpoint drawn between them. A new high or low '
                             'pushing against the edge of the channel is read as a breakout from '
                             'the recent trading range.',
              'wiki': 'https://www.investopedia.com/terms/d/donchianchannels.asp',
              'param_labels': {'period': 'Length'},
              'param_steps': {}},
 'vwap': {'group': 'Anchored & volume',
          'full': 'Volume-weighted avg price',
          'desc': 'Cumulative typical-price-weighted mean of the window.',
          'description': 'Tracks the average price paid for the security, weighted by how much '
                         'volume traded at each price, accumulated from the start of the visible '
                         'window. Price above VWAP suggests buyers are paying a premium to the '
                         "session's average cost; price below suggests a discount.",
          'wiki': 'https://www.investopedia.com/terms/v/vwap.asp',
          'param_labels': {},
          'param_steps': {}},
 'avwap': {'group': 'Anchored & volume',
           'full': 'Anchored VWAP',
           'desc': 'Trade-weighted mean from an anchored timestamp.',
           'description': 'The same volume-weighted average as VWAP, but the running average '
                          'starts fresh from a timestamp the trader chooses rather than from the '
                          'start of the chart. It is read as the average cost basis of everyone '
                          'who has traded since that anchor, useful for judging whether a specific '
                          'event still supports the price.',
           'wiki': None,
           'param_labels': {'anchor': 'Anchor'},
           'param_steps': {}},
 'volume': {'group': '',
            'full': '',
            'desc': '',
            'description': '',
            'wiki': None,
            'param_labels': {},
            'param_steps': {}},
 'macd': {'group': 'Momentum',
          'full': 'MACD',
          'desc': 'EMA(fast) − EMA(slow); signal is its EMA.',
          'description': 'Tracks the gap between a fast and a slow moving average, plus a signal '
                         'line that smooths that gap, to show shifts in trend momentum. A '
                         'crossover between the MACD and signal lines is read as a possible turn, '
                         "and the histogram's height shows how fast that momentum is building or "
                         'fading.',
          'wiki': 'https://www.investopedia.com/terms/m/macd.asp',
          'param_labels': {'fast': 'Fast EMA', 'slow': 'Slow EMA', 'signal': 'Signal'},
          'param_steps': {}},
 'stoch': {'group': 'Momentum',
           'full': 'Stochastic',
           'desc': 'Close position in the N-bar high–low range.',
           'description': 'Compares the latest close to the high-low range over the lookback '
                          'window, on a 0-100 scale, to show where price sits within its recent '
                          'range. Readings near the top are read as overbought and readings near '
                          'the bottom as oversold; a crossover of its two lines is often read as a '
                          'timing signal.',
           'wiki': 'https://www.investopedia.com/terms/s/stochasticoscillator.asp',
           'param_labels': {'k': '%K period', 'smooth_k': '%K smoothing', 'd': '%D period'},
           'param_steps': {}},
 'stochrsi': {'group': 'Momentum',
              'full': 'StochRSI',
              'desc': 'Stochastic formula applied to RSI.',
              'description': 'Applies the same overbought/oversold calculation used by the '
                             'stochastic oscillator to RSI values instead of price, producing a '
                             'more sensitive, faster-moving 0-100 reading. It is read the same way '
                             'as RSI or stochastics, but reaches its extremes more often and '
                             'sooner.',
              'wiki': 'https://www.investopedia.com/terms/s/stochrsi.asp',
              'param_labels': {'period': 'RSI length', 'stoch_period': 'Stoch period'},
              'param_steps': {}},
 'adx': {'group': 'Trend strength',
         'full': 'ADX / DMI',
         'desc': 'Wilder trend strength with ±DI direction.',
         'description': 'Measures how strongly price is trending, regardless of direction, '
                        'alongside two companion lines showing whether buyers or sellers currently '
                        'have the upper hand. A rising main line is read as a strengthening trend, '
                        'while a low reading suggests a directionless, choppy market.',
         'wiki': 'https://www.investopedia.com/terms/a/adx.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'cci': {'group': 'Momentum',
         'full': 'Commodity Channel Index',
         'desc': 'Typical price vs its SMA, in MAD units.',
         'description': 'Measures how far the typical price has strayed from its recent average, '
                        'scaled by typical deviation, so it reads similarly across different '
                        'securities and price levels. Large positive or negative readings are read '
                        'as a price move stretched well beyond its normal range.',
         'wiki': 'https://www.investopedia.com/terms/c/commoditychannelindex.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'willr': {'group': 'Momentum',
           'full': 'Williams %R',
           'desc': 'Inverted 0…−100 close-in-range oscillator.',
           'description': 'Compares the latest close to the high-low range over the lookback '
                          'window, similar to the stochastic oscillator but plotted upside down on '
                          'a 0 to -100 scale. Readings near zero are read as overbought and '
                          'readings near -100 as oversold.',
           'wiki': 'https://www.investopedia.com/terms/w/williamsr.asp',
           'param_labels': {'period': 'Length'},
           'param_steps': {}},
 'roc': {'group': 'Momentum',
         'full': 'Rate of Change',
         'desc': 'Percent change vs N bars ago.',
         'description': 'The plain percentage change in price from a fixed number of bars ago to '
                        'now, a direct measure of how fast price is moving. Crossing above or '
                        'below zero is read as momentum turning positive or negative.',
         'wiki': 'https://www.investopedia.com/terms/p/pricerateofchange.asp',
         'param_labels': {'period': 'Length'},
         'param_steps': {}},
 'obv': {'group': 'Volume',
         'full': 'On Balance Volume',
         'desc': 'Running sum of signed volume.',
         'description': "A running total of volume that adds the bar's volume on an up day and "
                        'subtracts it on a down day, tracking whether volume is flowing with '
                        'buyers or sellers. A rising line alongside rising price is read as buying '
                        'pressure confirming the trend; a divergence between the two is read as a '
                        'warning sign.',
         'wiki': 'https://www.investopedia.com/terms/o/onbalancevolume.asp',
         'param_labels': {},
         'param_steps': {}},
 'stddev': {'group': 'Volatility',
            'full': 'Standard Deviation',
            'desc': 'Population σ of closes.',
            'description': 'The statistical spread of price around its recent average, computed '
                           'the same way as the width used inside the Bollinger Bands. A rising '
                           'value is read as expanding volatility and a falling value as price '
                           'settling into a tighter range.',
            'wiki': 'https://www.investopedia.com/terms/s/standarddeviation.asp',
            'param_labels': {'period': 'Length'},
            'param_steps': {}},
 'pct_b': {'group': 'Volatility',
           'full': '%B',
           'desc': 'Close position within the Bollinger bands.',
           'description': 'Shows where the current price sits between the Bollinger Bands, '
                          'expressed as a fraction from 0 at the lower band to 1 at the upper '
                          'band. Readings above 1 or below 0 mean price has pushed outside the '
                          'bands entirely, read as an extreme move.',
           'wiki': 'https://en.wikipedia.org/wiki/Bollinger_Bands',
           'param_labels': {'period': 'Length', 'k': 'StdDev multiplier'},
           'param_steps': {'k': 0.5}},
 'bandwidth': {'group': 'Volatility',
               'full': 'Bollinger BandWidth',
               'desc': '(upper − lower) ÷ mid — squeeze gauge.',
               'description': 'The width of the Bollinger Bands expressed as a percentage of the '
                              'middle band, so it rises when volatility expands and falls when it '
                              'contracts. A sustained low reading is often read as a volatility '
                              'squeeze that tends to precede a bigger move.',
               'wiki': 'https://en.wikipedia.org/wiki/Bollinger_Bands',
               'param_labels': {'period': 'Length', 'k': 'StdDev multiplier'},
               'param_steps': {'k': 0.5}},
 'sar': {'group': 'Trend',
         'full': 'Parabolic SAR',
         'desc': 'Wilder stop-and-reverse dots. Path-dependent.',
         'description': 'Plots a series of dots that trail below price in an uptrend and above it '
                        'in a downtrend, accelerating toward price the longer the trend runs. When '
                        'price crosses the dots, it flips to the other side and is commonly read '
                        'as a signal to reverse position.',
         'wiki': 'https://www.investopedia.com/terms/p/parabolicindicator.asp',
         'param_labels': {'acceleration': 'Accel. step', 'maximum': 'Accel. max'},
         'param_steps': {'acceleration': 0.01, 'maximum': 0.01}}}


_FIELDS = ("group", "full", "desc", "description", "wiki", "param_labels", "param_steps")


def catalog() -> list[dict]:
    """The registry as the widget's catalog. The frontend never hardcodes this; if the two
    disagree the registry wins and the catalog is regenerated -- which this function is."""
    out = []
    for ind in REGISTRY.values():
        if ind.name == "volume":            # raw bar data, not a study
            continue
        meta = {f: getattr(ind, f) for f in _FIELDS} | PICKER.get(ind.name, {})
        outputs = list(ind.render)
        types = {r.get("type", "line") for r in ind.render.values()}
        shared = catalog_entry(ind)
        out.append({
            "param_schema": shared["param_schema"],
            "definition_version": shared["definition_version"],
            "outputs": list(ind.render),
            "name": ind.name, "label": ind.label, "pane": ind.pane,
            "price_basis": ind.price_basis, "convention": ind.convention,
            # Studies-picker metadata (v12.3.1): the long name falls back to
            # the short label so an indicator that somehow ships without one
            # still renders a real name rather than an empty string. "title"
            # is the same string under the older key, kept for one release
            # so a client built against B1's projection keeps working.
            "group": meta["group"], "full": meta["full"] or ind.label,
            "title": meta["full"] or ind.label, "desc": meta["desc"],
            "description": meta["description"], "wiki": meta["wiki"],
            # "float" travels alongside the value: the client re-renders an
            # expression as text and must print a float default with its
            # trailing `.0` (BBANDS(20, 2.0), studies addendum S2.4), but a
            # JSON number loses the int/float distinction crossing into JS
            # (2.0 and 2 both decode to `2`) -- so the registry says it here.
            # "window" is the same story for `ind.windows` (v12.3.0): the
            # client's parser has to normalise a `bd` unit onto every window
            # parameter and refuse it on a non-window (resolve()'s stray/bare
            # checks), so it needs the same yes/no per parameter here
            # rather than re-deriving it. "windows" alongside it names the
            # set directly, since a client comparing parameter names against
            # it is simpler than filtering the per-param flag -- both are
            # sent so the client can use whichever is easier, not because the
            # information differs.
            "windows": list(ind.windows),
            # "label" is the editor's human name for the parameter, falling
            # back to the raw name; "step" is the spinner increment and is
            # sent for float parameters only -- an int steps by 1 and the
            # client needs no instruction for that.
            "params": [{"name": k, "default": v, "text": v is None or isinstance(v, str),
                        "float": isinstance(v, float), "window": k in ind.windows,
                        "label": meta["param_labels"].get(k, k),
                        **({"step": meta["param_steps"][k]}
                           if isinstance(v, float) and k in meta["param_steps"] else {})}
                       for k, v in ind.params.items()],
            "guides": list(ind.guides),
            "band": any(o.endswith("_up") for o in outputs) and any(o.endswith("_lo") for o in outputs),
            "render": "dots" if "scatter" in types else "bar" if "bar" in types else "line",
            "colors": {o: r.get("color") for o, r in ind.render.items()},
            # The per-output pen and the band's fill defaults, for the picker
            # to seed from; the pen also rides each series' own `render` on
            # the wire, which is what the chart draws by.
            "pens": {o: r.get("pen", "solid") for o, r in ind.render.items()},
            "widths": {o: r.get("width", 1) for o, r in ind.render.items()},
            "shade": ind.shade, "fill_opacity": ind.fill_opacity,
            "fill_pattern": ind.fill_pattern,
            # Sessioned studies render as steps (addendum §6): the client
            # needs to know, and the registry is the only place that does.
            "sessioned": ind.sessioned,
            # S14: the card stores each time parameter as {expr, at}; empty is left out.
            **({"times": list(ind.times)} if ind.times else {}),
            # A cross-symbol study's ticker parameter (spec 2026-11-13 cross-symbol §5): the client
            # resolves it like a series symbol; empty is left out.
            **({"tickers": list(ind.tickers)} if ind.tickers else {}),
            # A repainting indicator's history can change after the fact
            # (spec D10); the Charts MCP shows it on each study's capability
            # so a model knows not to trust an old value of one.
            "repaints": ind.repaints,
            "eodhd": None if ind.eodhd is None else {"function": ind.eodhd.function,
                                                     "note": ind.eodhd.note},
        })
    return out
