# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Route watchlist symbols to EODHD websocket feeds and REST tickers."""

import re

FEEDS = ("us", "crypto", "forex")

# Currency codes recognized on EODHD's forex feed (both halves of a pair).
_CCY = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
    "ILS", "THB", "KRW", "INR", "BRL",
}

_SNAPSHOT_SUFFIX = {"us": ".US", "crypto": ".CC", "forex": ".FOREX"}


def classify(symbol: str) -> str:
    """Asset class of a bare symbol: 'crypto' | 'forex' | 'us', or 'futures' (CL=F).

    'futures' is history only (openbb_client.history_route): it is not in FEEDS, and
    normalize() refuses the '=' so no futures symbol is ever subscribed.
    """
    s = symbol.strip().upper()
    if s.endswith("=F"):
        return "futures"
    if "-" in s:
        return "crypto"
    if len(s) == 6 and s[:3] in _CCY and s[3:] in _CCY:
        return "forex"
    return "us"


# What the EODHD websocket SDK accepts, as this app writes symbols (upper case): its own check
# is ^[A-z0-9-$]{1,48}$, whose A-z range also spans ^ and _. No '.', so never an
# exchange-qualified ticker -- one of those in a feed's set made the SDK refuse the whole set.
_FEED_SYMBOL_RE = re.compile(r"[A-Z0-9^_$-]{1,48}")


def normalize(symbol) -> str | None:
    """The bare feed symbol, or None when the websocket feed cannot take it (L1).

    Symbols here are bare (snapshot_ticker adds the exchange), so a suffix naming the
    symbol's own feed is dropped (AAPL.US -> AAPL, BTC-USD.CC -> BTC-USD, EURUSD.FOREX ->
    EURUSD). Any other '.' (AAPL.LSE, BRK.B) or character the SDK refuses gives None.
    """
    s = str(symbol).strip().upper()
    for feed, suffix in _SNAPSHOT_SUFFIX.items():
        if s.endswith(suffix) and classify(s[: -len(suffix)]) == feed:
            s = s[: -len(suffix)]
            break
    return s if _FEED_SYMBOL_RE.fullmatch(s) else None


def split_by_feed(symbols: list[str]) -> dict[str, set[str]]:
    """Group cleaned (upper-cased, de-duplicated) symbols by feed; all feeds present.

    A symbol with no feed (futures) is dropped.
    """
    out: dict[str, set[str]] = {feed: set() for feed in FEEDS}
    for raw in symbols:
        s = str(raw).strip().upper()
        if s and classify(s) in out:
            out[classify(s)].add(s)
    return out


def snapshot_ticker(symbol: str) -> str:
    """Exchange-qualified ticker for the REST /real-time snapshot (AAPL -> AAPL.US).

    ValueError for a symbol EODHD has no snapshot for (futures); both callers degrade
    to a blank row on it.
    """
    s = symbol.strip().upper()
    suffix = _SNAPSHOT_SUFFIX.get(classify(s))
    if suffix is None:
        raise ValueError(f"no EODHD snapshot for {s}")
    return s + suffix
