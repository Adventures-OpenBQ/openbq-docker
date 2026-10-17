# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Recent closed minute bars from EODHD's real-time service, for filling the
minutes a restarted live-grid did not hear (user ruling 2026-10-17: fetched
at query time, see build_series' `gap_key`).

`GET ws.eodhistoricaldata.com/history?market=us&symbol=AAPL` answers the last
~120 traded minutes as 1m bars built from the same EDGX trade stream the
websocket carries, so a filled minute matches its tick-built neighbours in
venue and volume. US equities only (crypto and forex answer an empty list).

Probed 2026-10-17: `t` is milliseconds on older bars and nanoseconds on the
newest, and the newest is stamped with its last trade, not its minute -- the
bar still forming. Stamps are normalised and an unaligned one is dropped.
"""

from datetime import datetime, timedelta

HISTORY_URL = "https://ws.eodhistoricaldata.com/history"
_EPOCH = datetime(1970, 1, 1)


def _stamp(t) -> datetime | None:
    """A bar-open time as naive UTC, from ms or ns; None if not on a minute."""
    try:
        t = int(t)
    except (TypeError, ValueError):
        return None
    ms = t // 10**6 if t > 10**15 else t
    if ms % 60_000:
        return None
    return _EPOCH + timedelta(milliseconds=ms)


def parse_history(raw) -> list[dict]:
    """The service's bars as history rows (`date` a naive UTC datetime)."""
    rows = []
    for bar in raw if isinstance(raw, list) else []:
        if not isinstance(bar, dict):
            continue
        stamp = _stamp(bar.get("t"))
        if stamp is None or any(bar.get(k) is None for k in "ohlc"):
            continue
        rows.append({"date": stamp, "open": bar["o"], "high": bar["h"], "low": bar["l"],
                     "close": bar["c"], "volume": bar.get("v")})
    return rows


async def recent_minutes(symbol: str, key: str) -> list[dict]:
    """The recent closed 1m bars for one US equity. Errors never carry the URL:
    it holds the API key."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(HISTORY_URL, params={
                "market": "us", "symbol": symbol, "api_token": key})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"recent minute bars unreachable: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise RuntimeError(f"recent minute bars answered HTTP {response.status_code}")
    return parse_history(response.json())
