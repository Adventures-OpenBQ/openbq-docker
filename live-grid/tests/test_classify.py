# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Tests for app.classify."""

import pytest

from app.classify import FEEDS, classify, snapshot_ticker, split_by_feed


class TestClassify:
    def test_feeds_constant(self):
        assert FEEDS == ("us", "crypto", "forex")

    def test_plain_equity(self):
        assert classify("AAPL") == "us"

    def test_lowercase_equity(self):
        assert classify("aapl") == "us"

    def test_crypto_dash(self):
        assert classify("BTC-USD") == "crypto"

    def test_forex_pair(self):
        assert classify("EURUSD") == "forex"

    def test_six_letter_equity_not_forex(self):
        # 6 letters but halves are not both currency codes -> equity
        assert classify("GOOGLX") == "us"

    def test_five_letter_equity(self):
        assert classify("GOOGL") == "us"


class TestSplitByFeed:
    def test_groups_and_cleans(self):
        out = split_by_feed([" aapl ", "BTC-USD", "eurusd", "AAPL", ""])
        assert out == {"us": {"AAPL"}, "crypto": {"BTC-USD"}, "forex": {"EURUSD"}}

    def test_all_feeds_always_present(self):
        assert set(split_by_feed([]).keys()) == {"us", "crypto", "forex"}


class TestSnapshotTicker:
    def test_us(self):
        assert snapshot_ticker("AAPL") == "AAPL.US"

    def test_crypto(self):
        assert snapshot_ticker("btc-usd") == "BTC-USD.CC"

    def test_forex(self):
        assert snapshot_ticker("EURUSD") == "EURUSD.FOREX"


def test_normalize_strips_the_feeds_own_exchange_suffix_and_refuses_what_the_sdk_would():
    """L1 (NAS, 2026-10-16): the app's symbols are bare (snapshot_ticker adds the suffix), and
    the EODHD websocket SDK refuses any '.' (^[A-z0-9-$]{1,48}$)."""
    from app.classify import normalize

    assert normalize(" aapl.us ") == "AAPL"
    assert normalize("BTC-USD.CC") == "BTC-USD"
    assert normalize("EURUSD.FOREX") == "EURUSD"
    assert normalize("^GSPC") == "^GSPC" and normalize("BTC-USD") == "BTC-USD"
    for bad in ("AAPL.LSE", "BRK.B", "AAPL.CC", "BTC-USD.US", "A B", "", "X" * 49, "AAPL/US"):
        assert normalize(bad) is None, bad


@pytest.mark.parametrize("symbol,kind", [
    ("CL=F", "futures"), ("cl=f", "futures"), ("AAPL", "us"), ("BTC-USD", "crypto"),
    ("EURUSD", "forex"),
])
def test_classify_table(symbol, kind):
    assert classify(symbol) == kind


def test_a_futures_symbol_has_no_feed_snapshot_or_feed_form():
    """Futures are history only (Ep 10, CL=F): never fed, never snapshotted, never subscribed."""
    from app.classify import normalize

    assert "futures" not in FEEDS
    assert split_by_feed(["CL=F", "AAPL"]) == {"us": {"AAPL"}, "crypto": set(), "forex": set()}
    with pytest.raises(ValueError):
        snapshot_ticker("CL=F")
    assert normalize("CL=F") is None
