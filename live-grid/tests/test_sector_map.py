# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""S&P 500 sector map: SPY weights x sector-ETF day change, as a treemap."""

import pytest

from app import sector_map
from app.sector_map import (
    SECTOR_ETFS,
    WeightsUnavailable,
    build_sector_figure,
    fetch_weights,
)

# The live SPY.US response on 2026-10-15, trimmed to the shape EODHD returns.
SPY_WEIGHTS = {
    "Basic Materials": {"Equity_%": 1.4968},
    "Consumer Cyclicals": {"Equity_%": 9.0813},
    "Financial Services": {"Equity_%": 11.8047},
    "Real Estate": {"Equity_%": 1.6776},
    "Communication Services": {"Equity_%": 9.7868},
    "Energy": {"Equity_%": 3.462},
    "Industrials": {"Equity_%": 7.3468},
    "Technology": {"Equity_%": 41.2029},
    "Consumer Defensive": {"Equity_%": 4.5084},
    "Healthcare": {"Equity_%": 9.3217},
    "Utilities": {"Equity_%": 1.9114},
}


class FakeFundamentals:
    def __init__(self, payload=None, exc=None):
        self.payload = SPY_WEIGHTS if payload is None else payload
        self.exc = exc
        self.calls = []

    def get_fundamentals_data(self, ticker, filter):
        self.calls.append((ticker, filter))
        if self.exc:
            raise self.exc
        return self.payload


@pytest.fixture(autouse=True)
def _clear_cache():
    sector_map._reset_cache_for_tests()
    yield
    sector_map._reset_cache_for_tests()


def test_eleven_sectors_map_to_the_spdr_etfs():
    assert sorted(SECTOR_ETFS.values()) == sorted(
        ["XLK", "XLF", "XLV", "XLY", "XLC", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB"]
    )
    assert set(SECTOR_ETFS) == set(SPY_WEIGHTS)


def test_fetch_weights_reads_equity_percent_with_the_spy_filter():
    client = FakeFundamentals()
    w = fetch_weights(client, now=0.0)
    assert w["Technology"] == 41.2029
    assert len(w) == 11
    assert client.calls == [("SPY.US", "ETF_Data::Sector_Weights")]


def test_weights_accept_string_values():
    payload = {k: {"Equity_%": str(v["Equity_%"])} for k, v in SPY_WEIGHTS.items()}
    assert fetch_weights(FakeFundamentals(payload), now=0.0)["Energy"] == 3.462


def test_weights_are_cached_for_a_day():
    client = FakeFundamentals()
    fetch_weights(client, now=0.0)
    fetch_weights(client, now=24 * 3600.0 - 1)
    assert len(client.calls) == 1
    fetch_weights(client, now=24 * 3600.0 + 1)
    assert len(client.calls) == 2


def test_missing_sector_raises_naming_it():
    payload = {k: v for k, v in SPY_WEIGHTS.items() if k != "Consumer Cyclicals"}
    with pytest.raises(WeightsUnavailable, match="Consumer Cyclicals"):
        fetch_weights(FakeFundamentals(payload), now=0.0)


def test_vendor_error_raises_weights_unavailable():
    with pytest.raises(WeightsUnavailable):
        fetch_weights(FakeFundamentals(exc=RuntimeError("402 quota")), now=0.0)


def test_failure_is_cached_briefly():
    client = FakeFundamentals(exc=RuntimeError("402 quota"))
    for now in (0.0, 15.0, 299.0):
        with pytest.raises(WeightsUnavailable):
            fetch_weights(client, now=now)
    assert len(client.calls) == 1, "a failing vendor must not be hit every poll"
    client.exc = None
    assert fetch_weights(client, now=301.0)["Technology"] == 41.2029


def _weights():
    return {k: v["Equity_%"] for k, v in SPY_WEIGHTS.items()}


def test_figure_is_one_treemap_sized_by_weight_coloured_by_percent():
    changes = {etf: 0.0 for etf in SECTOR_ETFS.values()}
    changes["XLK"] = 0.0084
    changes["XLE"] = -0.021
    fig = build_sector_figure(_weights(), changes)
    assert len(fig["data"]) == 1
    t = fig["data"][0]
    assert t["type"] == "treemap"
    i = t["labels"].index("Technology")
    assert t["values"][i] == 41.2029
    assert t["parents"] == [""] * 11
    assert t["marker"]["colors"][i] == pytest.approx(0.84)
    assert t["text"][i] == "XLK<br>41.2% · +0.84%"
    e = t["labels"].index("Energy")
    assert t["text"][e] == "XLE<br>3.5% · -2.10%"
    assert t["marker"]["cmid"] == 0
    assert t["marker"]["cmax"] == pytest.approx(2.1)
    assert t["marker"]["cmin"] == pytest.approx(-2.1)


def test_small_moves_keep_a_one_percent_colour_range():
    changes = {etf: 0.001 for etf in SECTOR_ETFS.values()}
    t = build_sector_figure(_weights(), changes)["data"][0]
    assert (t["marker"]["cmin"], t["marker"]["cmax"]) == (-1.0, 1.0)


def test_missing_change_stays_as_a_grey_na_tile():
    changes = {etf: 0.01 for etf in SECTOR_ETFS.values()}
    changes["XLU"] = None
    t = build_sector_figure(_weights(), changes)["data"][0]
    u = t["labels"].index("Utilities")
    assert len(t["labels"]) == 11, "dropping a tile would resize the others"
    assert t["values"][u] == 1.9114
    assert t["marker"]["colors"][u] == 0
    assert t["text"][u] == "XLU<br>1.9% · n/a"


def test_all_changes_missing_draws_grey():
    t = build_sector_figure(_weights(), {})["data"][0]
    assert t["marker"]["colors"] == [0] * 11
    assert (t["marker"]["cmin"], t["marker"]["cmax"]) == (-1.0, 1.0)
