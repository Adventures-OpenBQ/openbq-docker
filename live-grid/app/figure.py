# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Plotly figure JSON. The client renders it -- this image has no chart backend."""


def _x(date):
    """A bar date as JSON: bars built from kdb+ ticks carry datetimes (pandas Timestamps),
    which JSONResponse cannot serialise, so /chart answered 500 once live bars joined."""
    return date if date is None or isinstance(date, str) else date.isoformat()


def build_figure(symbol: str, bars: list[dict]) -> dict:
    """A candlestick figure for the given bars."""
    return {
        "data": [
            {
                "type": "candlestick",
                "name": symbol,
                "x": [_x(b.get("date")) for b in bars],
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
