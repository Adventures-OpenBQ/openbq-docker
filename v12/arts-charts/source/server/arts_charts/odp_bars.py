# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Bars from openbq-docker's ODP REST API: the yfinance or the EODHD history route.

openbq-docker installs no openbb-equity package; its yfinance history is the
openbq-yfinance router extension's `GET /api/v1/yfinance/equity/historical`,
and EODHD's is the openbq-eodhd namespace, one route per asset class
(`/api/v1/eodhd/<equity|crypto|currency>/price/historical`). Either supplies
OHLCV bars only -- every study is computed locally. Pointing ARTS_CHARTS_ODP_URL
at the v11 provider host captures both into TemporalDB with no change here.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from arts_charts.classify import classify
from arts_charts.ta.session import is_intraday

YFINANCE_PATH = "/api/v1/yfinance/equity/historical"

#: Wire interval -> the provider's interval of the same width. A bar width is never
#: resampled: anything a provider does not list is refused.
INTERVALS = {
    # Exactly the widths openbq-yfinance 0.1.0 lists (models/prices.py,
    # HistoricalQuery.interval) that the client's and the engine's `<n><s|m|h|d|w>`
    # grammar can name; `1w` is yfinance's `1wk`, renamed. `1mo`/`3mo` have no spelling.
    "yfinance": {
        "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m",
        "90m": "90m", "1h": "1h", "1d": "1d", "5d": "5d", "1w": "1wk",
    },
    # openbq-eodhd models/_bars.py INTERVAL_CHOICES (1m 5m 1h 1d 1W 1M), as the
    # grammar spells them; `1M` has no spelling.
    "eodhd": {"1m": "1m", "5m": "5m", "1h": "1h", "60m": "1h", "1d": "1d", "1w": "1W"},
}

#: The asset class's EODHD route, as live-grid's openbb_client.history_route picks it
#: (openbq-docker live-grid/app/openbb_client.py _HISTORICAL_PATH): crypto and forex by
#: their shape, everything else equity.
EODHD_CLASS = {"crypto": "crypto", "forex": "currency"}

#: live-grid's metadata block for an answer that carried none (openbb_client._UNKNOWN).
UNKNOWN_META = {
    "cache": "unknown", "rows_from_cache": 0, "rows_from_upstream": 0,
    "gaps_fetched": 0, "upstream_ms": 0.0, "kdb_ms": 0.0,
}


class Refused(ValueError):
    """A request this server cannot serve: a 400 on HTTP, a 1011 close on a socket."""


class NotConfigured(ValueError):
    """A provider this server has no history source for: a 422 on HTTP, a 1011 close."""


def check_interval(interval: str, provider: str = "yfinance") -> None:
    """Refuse an interval `provider` does not list. A provider with no table here
    (temporaldb) is its own source's to judge."""
    served = INTERVALS.get(provider)
    if served is not None and interval not in served:
        raise Refused(f"interval {interval!r} is not served by {provider}; "
                      f"served: {', '.join(served)}")


def history_path(symbol: str, provider: str) -> str:
    if provider == "yfinance":
        return YFINANCE_PATH
    return f"/api/v1/eodhd/{EODHD_CLASS.get(classify(symbol), 'equity')}/price/historical"


class OdpBars:
    """`await bars(symbol, interval, start, end) -> (bars, meta)` from one provider,
    the shape live-grid's fetch_series returned, over one inclusive window."""

    def __init__(self, base_url: str, auth: tuple[str, str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 provider: str = "yfinance"):
        if provider not in INTERVALS:
            raise ValueError(f"OdpBars serves {', '.join(INTERVALS)}, not {provider!r}")
        self._base = base_url.rstrip("/")
        self._auth, self._transport, self._provider = auth, transport, provider

    async def __call__(self, symbol: str, interval: str, start: str, end: str):
        check_interval(interval, self._provider)
        last = date.fromisoformat(end[:10])
        if self._provider == "yfinance":
            # yfinance's end_date is EXCLUSIVE (start_date must precede it); the
            # router's window is inclusive, so a one-day window still has a day.
            last += timedelta(days=1)
        # EODHD's is inclusive: openbq-eodhd reads it to the end of that UTC day.
        params = {
            "symbol": symbol, "provider": self._provider,
            "interval": INTERVALS[self._provider][interval],
            "start_date": start[:10], "end_date": last.isoformat(),
        }
        async with httpx.AsyncClient(timeout=60.0, auth=self._auth,
                                     transport=self._transport) as client:
            response = await client.get(self._base + history_path(symbol, self._provider),
                                        params=params)
            response.raise_for_status()
            payload = response.json()
        bars = payload.get("results") or []
        if not is_intraday(interval):
            # A daily yfinance bar is stamped at local midnight WITH an offset;
            # as an instant it lands the evening before or 04:00 UTC. A
            # session's bar is its date, as live-grid's daily history always was.
            bars = [{**bar, "date": str(bar.get("date"))[:10]} for bar in bars]
        meta = (payload.get("extra") or {}).get("results_metadata") or dict(UNKNOWN_META)
        return bars, meta
