# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Plotly figure JSON. The client renders it -- this image has no chart backend."""


from app.market_time import wire_time


def _x(value, *, date_only=False):
    return wire_time(value, date_only=date_only)


def build_figure(symbol: str, bars: list[dict], interval: str | None = None) -> dict:
    """A candlestick figure for the given bars."""
    from app.series import intraday
    date_only = interval is not None and not intraday(interval)
    return {
        "data": [
            {
                "type": "candlestick",
                "name": symbol,
                "x": [_x(b.get("date"), date_only=date_only) for b in bars],
                "open": [b.get("open") for b in bars],
                "high": [b.get("high") for b in bars],
                "low": [b.get("low") for b in bars],
                "close": [b.get("close") for b in bars],
            }
        ],
        "layout": {
            "title": {"text": f"{symbol} — served through the kdb+ cache"},
            "xaxis": {"rangeslider": {"visible": False}},
            "margin": {"l": 40, "r": 20, "t": 40, "b": 40},
            "template": "plotly_dark",
        },
    }
