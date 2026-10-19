# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""S&P 500 sector map: SPY's sector weights x each sector SPDR's day change.

Weights come from EODHD's SPY.US fundamentals, which use Morningstar sector
names; the ETFs follow GICS. The 11 buckets line up by name, but individual
companies can sit in different buckets, so this is a teaching map, not an
index replica.
"""

import logging
import math
import time
from typing import Any

from app.quotes import QuoteTable

log = logging.getLogger(__name__)

# EODHD (Morningstar) sector name -> SPDR sector ETF. Checked against the live
# SPY.US response on 2026-10-15.
SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclicals": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}

_FILTER = "ETF_Data::Sector_Weights"
_TTL = 24 * 3600.0
_NEG_TTL = 300.0  # a failing vendor is retried every 5 min, not every 15 s poll
_COLORSCALE = [[0.0, "#d32f2f"], [0.5, "#555555"], [1.0, "#2e7d32"]]

_RESEED_S = 300.0

# "weights" -> (dict | WeightsUnavailable, expiry on the monotonic clock)
_cache: dict[str, tuple[Any, float]] = {}
# ETF -> when this route last seeded it, or first saw it already warm
_seeded_at: dict[str, float] = {}


class WeightsUnavailable(Exception):
    """SPY's sector weights could not be read; the route answers 502."""


def _reset_cache_for_tests() -> None:
    _cache.clear()
    _seeded_at.clear()


def etfs_to_seed(rows: dict[str, dict], now: float) -> list[str]:
    """The ETFs this poll should REST-seed. Marks them as seeded at `now`.

    Only QuoteTable.seed sets a previous close, so every ETF is re-seeded at
    most every _RESEED_S: that rolls the "day change" over on a long-running
    process, and backs off an ETF whose seed failed instead of retrying it on
    every 15 s poll. An ETF first seen already warm (the grid seeded it) waits
    one interval like any other.
    """
    due = []
    for etf in SECTOR_ETFS.values():
        last = _seeded_at.get(etf)
        cold = rows.get(etf, {}).get("change_percent") is None
        if last is None and not cold:
            _seeded_at[etf] = now
        elif last is None or now - last >= _RESEED_S:
            _seeded_at[etf] = now
            due.append(etf)
    return due


def _read(resp: Any) -> dict[str, float]:
    if not isinstance(resp, dict):
        raise WeightsUnavailable("SPY.US sector weights: unexpected response")
    weights: dict[str, float] = {}
    for name in SECTOR_ETFS:
        try:
            w = float(resp[name]["Equity_%"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(w) and w > 0:
            weights[name] = w
    missing = [name for name in SECTOR_ETFS if name not in weights]
    if missing:
        raise WeightsUnavailable("SPY.US sector weights missing: " + ", ".join(missing))
    return weights


def fetch_weights(client, now: float | None = None) -> dict[str, float]:
    """Sector name -> % of SPY. Raises WeightsUnavailable; never invents weights."""
    now = time.monotonic() if now is None else now
    hit = _cache.get("weights")
    if hit and hit[1] > now:
        if isinstance(hit[0], WeightsUnavailable):
            raise WeightsUnavailable(str(hit[0]))  # fresh: a shared one grows its traceback
        return hit[0]
    try:
        weights = _read(client.get_fundamentals_data(ticker="SPY.US", filter=_FILTER))
    except WeightsUnavailable as exc:
        _cache["weights"] = (exc, now + _NEG_TTL)
        raise
    except Exception as exc:  # noqa: BLE001 - any vendor failure is a 502, not a crash
        err = WeightsUnavailable(f"SPY.US sector weights: {exc}")
        _cache["weights"] = (err, now + _NEG_TTL)
        raise err from exc
    _cache["weights"] = (weights, now + _TTL)
    return weights


def build_sector_figure(weights: dict[str, float], changes: dict[str, float | None]) -> dict:
    """One treemap: area = weight, colour = day % change (changes are fractions)."""
    labels, values, colors, text = [], [], [], []
    known: list[float] = []
    for name, etf in SECTOR_ETFS.items():
        frac = changes.get(etf)
        pct = frac * 100 if isinstance(frac, (int, float)) and math.isfinite(frac) else None
        w = weights[name]
        labels.append(name)
        values.append(w)
        if pct is None:
            colors.append(0)  # the scale's grey midpoint
            text.append(f"{etf}<br>{w:.1f}% · n/a")
        else:
            known.append(abs(pct))
            colors.append(pct)
            text.append(f"{etf}<br>{w:.1f}% · {pct:+.2f}%")
    bound = max(known + [1.0])
    return {
        "data": [
            {
                "type": "treemap",
                "labels": labels,
                "parents": [""] * len(labels),
                "values": values,
                "branchvalues": "total",
                "text": text,
                "textinfo": "label+text",
                "hoverinfo": "label+text",
                "marker": {
                    "colors": colors,
                    "colorscale": _COLORSCALE,
                    "cmin": -bound,
                    "cmax": bound,
                    "showscale": True,
                },
            }
        ],
        "layout": {
            "title": {"text": "S&P 500 sectors — weight × day change"},
            "margin": {"l": 10, "r": 10, "t": 40, "b": 10},
            "template": "plotly_dark",
        },
    }


def refresh_prev_close(quotes: QuoteTable, symbols: list[str], client) -> None:
    """Re-read each symbol's previous close without touching its live row.

    QuoteTable.seed would also overwrite the price, volume and day range with
    EODHD's delayed REST snapshot, so seed a scratch table and take only the
    previous close from it, then re-derive the change from the live price.
    """
    scratch = QuoteTable()
    scratch.seed(symbols, client)
    for sym in symbols:
        prev = scratch._prev_close.get(sym)
        row = quotes.rows.get(sym)
        if not prev or not row or row.get("price") is None:
            continue
        quotes._prev_close[sym] = prev
        row["change"] = row["price"] - prev
        row["change_percent"] = (row["price"] - prev) / prev
