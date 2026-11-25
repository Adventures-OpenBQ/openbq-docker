# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""One fixed /ta_chart series for the show_seam tests: history, two flushed days, live bars."""

from datetime import datetime, timedelta


def _bar(day: datetime, close: float) -> dict:
    return {"date": day, "open": close - 1, "high": close + 1, "low": close - 2,
            "close": close, "volume": 1000.0}


_T0 = datetime(2026, 10, 12)
BARS = [_bar(_T0 + timedelta(days=i), 100.0 + i) for i in range(7)]
META = {
    "cache": "unknown", "rows_from_cache": 0, "rows_from_upstream": 0,
    "rows_from_lake": 2, "lake_days": ["2026-10-15", "2026-10-16"],
    "rows_from_ticks": 2, "seam": "2026-10-17T00:00:00",
}


def patch(monkeypatch, meta=None):
    """Make app.main.build_series answer BARS with `meta` (default META)."""
    import app.main

    async def fake(*args, **kwargs):
        return list(BARS), dict(META if meta is None else meta)

    monkeypatch.setattr(app.main, "build_series", fake)
