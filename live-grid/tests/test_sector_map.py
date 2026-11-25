# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""S&P 500 sector map: SPY weights x sector-ETF day change, as a treemap."""

import pytest

from app import sector_map
from app.sector_map import (
    SECTOR_ETFS,
    WeightsUnavailable,
    build_sector_figure,
    etfs_to_seed,
    fetch_weights,
    refresh_prev_close,
)
from app.quotes import QuoteTable

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


def test_a_cached_failure_raises_a_fresh_exception():
    client = FakeFundamentals(exc=RuntimeError("402 quota"))
    with pytest.raises(WeightsUnavailable) as first:
        fetch_weights(client, now=0.0)
    with pytest.raises(WeightsUnavailable) as second:
        fetch_weights(client, now=15.0)
    assert second.value is not first.value, "one shared exception grows its traceback per raise"
    assert str(second.value) == str(first.value)


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
    assert "cmid" not in t["marker"], "plotly ignores cmid once cmin/cmax are set"
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


# ---- re-seed policy -----------------------------------------------------
# Only QuoteTable.seed sets an ETF's previous close, so a long-running process
# must re-seed to roll the "day change" over, and a failed seed must not be
# retried on every 15 s poll.


def _rows(**changes):
    return {etf: {"change_percent": changes.get(etf)} for etf in SECTOR_ETFS.values()}


def test_first_poll_seeds_only_cold_etfs():
    rows = _rows(XLK=0.01)
    due = etfs_to_seed(rows, now=1000.0)
    assert "XLK" not in due
    assert len(due) == 10


def test_a_failed_seed_is_not_retried_every_poll():
    rows = _rows()
    assert len(etfs_to_seed(rows, now=1000.0)) == 11
    assert etfs_to_seed(rows, now=1015.0) == [], "a cold ETF waits out the backoff"
    assert len(etfs_to_seed(rows, now=1300.0)) == 11


def test_warm_etfs_are_reseeded_so_the_previous_close_rolls_over():
    rows = _rows(**{etf: 0.01 for etf in SECTOR_ETFS.values()})
    assert etfs_to_seed(rows, now=1000.0) == []
    assert etfs_to_seed(rows, now=1299.0) == []
    assert sorted(etfs_to_seed(rows, now=1300.0)) == sorted(SECTOR_ETFS.values())


def test_reseed_keeps_the_live_price_and_refreshes_the_previous_close():
    class Rest:
        def get_live_stock_prices(self, ticker):
            return {"close": "100", "previousClose": "90"}

    quotes = QuoteTable()
    row = quotes.rows.setdefault("XLK", {"symbol": "XLK"})
    row.update(price=189.3, change_percent=-0.006, day_high=191.0)
    quotes._prev_close["XLK"] = 190.43
    refresh_prev_close(quotes, ["XLK"], Rest())
    assert row["price"] == 189.3, "a live tick price must not fall back to the delayed REST close"
    assert row["day_high"] == 191.0
    assert quotes._prev_close["XLK"] == 90.0
    assert row["change_percent"] == pytest.approx((189.3 - 90) / 90)


# ---- route ---------------------------------------------------------------

from tests.test_main import FakeRest, make_client  # noqa: E402


class FakeRestWithWeights(FakeRest):
    def __init__(self, exc=None):
        super().__init__()
        self.exc = exc

    def get_fundamentals_data(self, ticker, filter):
        if self.exc:
            raise self.exc
        return SPY_WEIGHTS


def test_widget_is_a_polling_chart(monkeypatch):
    w = make_client(monkeypatch).get("/widgets.json").json()["sector_map"]
    assert w["type"] == "chart"
    assert w["endpoint"] == "sector_map"
    assert w["refetchInterval"] == 15000


def test_route_returns_the_treemap_and_leases_all_eleven(monkeypatch):
    client = make_client(monkeypatch, seed_client=FakeRestWithWeights())
    r = client.get("/sector_map")
    assert r.status_code == 200
    t = r.json()["data"][0]
    assert t["type"] == "treemap"
    i = t["labels"].index("Technology")
    # FakeRest's default snapshot: close 100, previousClose 90 -> +11.11%
    assert t["text"][i] == "XLK<br>41.2% · +11.11%"
    # app.state, not /health: /health reads recorder.store.session, which the
    # monkeypatched snapshot store make_client() installs does not have.
    assert client.app.state.leases.symbols() == sorted(SECTOR_ETFS.values())


def test_route_seeds_only_cold_etfs(monkeypatch):
    rest = FakeRestWithWeights()
    client = make_client(monkeypatch, seed_client=rest)
    row = client.app.state.quotes.rows.setdefault("XLK", {"symbol": "XLK"})
    row["change_percent"] = 0.005
    t = client.get("/sector_map").json()["data"][0]
    assert "XLK.US" not in rest.calls, "a warm quote must not cost a REST call"
    assert len(rest.calls) == 10
    assert t["text"][t["labels"].index("Technology")] == "XLK<br>41.2% · +0.50%"


def test_route_502_when_weights_fail(monkeypatch):
    client = make_client(monkeypatch, seed_client=FakeRestWithWeights(exc=RuntimeError("402")))
    r = client.get("/sector_map")
    assert r.status_code == 502
    assert r.json()["data"] == []
    assert "Sector map:" in r.json()["layout"]["title"]["text"]
    assert "SPY.US sector weights" in r.json()["detail"], "bdobb shows `detail`, not the title"


def test_route_reseeds_a_warm_etf_without_losing_its_live_price(monkeypatch):
    rest = FakeRestWithWeights()
    client = make_client(monkeypatch, seed_client=rest)
    row = client.app.state.quotes.rows.setdefault("XLK", {"symbol": "XLK"})
    row.update(price=120.0, change_percent=0.01)
    sector_map._seeded_at["XLK"] = float("-inf")  # due for its 5-minute re-seed
    t = client.get("/sector_map").json()["data"][0]
    assert "XLK.US" in rest.calls
    assert row["price"] == 120.0
    # FakeRest's previousClose is 90 -> (120 - 90) / 90
    assert t["text"][t["labels"].index("Technology")] == "XLK<br>41.2% · +33.33%"
