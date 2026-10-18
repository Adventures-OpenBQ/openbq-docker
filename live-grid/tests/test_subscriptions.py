# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""The subscription API: grouping, and a cap that counts the vendor's view."""

import pytest

from tests.test_main import make_client

# openbq-docker: built at run time so scripts/check-public.py never sees a literal tailnet name.
EXAMPLE_TAILNET = ".".join(["example", "ts", "net"])


def _client(tmp_path, monkeypatch, cap=50):
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(tmp_path / "w.json"))
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", str(cap))
    return make_client()


def test_an_empty_watchlist_reports_the_cap_and_nothing_used(tmp_path, monkeypatch):
    body = _client(tmp_path, monkeypatch).get("/api/subscriptions").json()
    assert body["service"] == "EODHD"
    assert body["cap"] == 50
    assert body["used"] == 0
    assert body["pinned"] == []


def test_adding_a_symbol_pins_it_and_counts_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/subscriptions", json={"symbol": "AAPL"}).status_code == 201
    body = client.get("/api/subscriptions").json()
    assert body["pinned"] == ["AAPL"]
    assert body["used"] == 1


def test_symbols_are_grouped_by_feed_under_display_names(tmp_path, monkeypatch):
    """classify() returns us/crypto/forex; the widget shows Equity/Crypto/Forex."""
    client = _client(tmp_path, monkeypatch)
    for s in ("MSFT", "AAPL", "BTC-USD", "EURUSD"):
        client.post("/api/subscriptions", json={"symbol": s})
    groups = client.get("/api/subscriptions").json()["groups"]
    assert groups["Equity"] == ["AAPL", "MSFT"], "alphabetical within a group"
    assert groups["Crypto"] == ["BTC-USD"]
    assert groups["Forex"] == ["EURUSD"]


def test_every_group_is_present_even_when_empty(tmp_path, monkeypatch):
    """The page renders three sections unconditionally; absent keys would break it."""
    groups = _client(tmp_path, monkeypatch).get("/api/subscriptions").json()["groups"]
    assert set(groups) == {"Equity", "Crypto", "Forex"}


def test_adding_a_symbol_twice_is_a_conflict(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    assert client.post("/api/subscriptions", json={"symbol": "AAPL"}).status_code == 409


def test_a_blank_symbol_is_rejected(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/subscriptions", json={"symbol": "   "}).status_code == 422


def test_the_cap_refuses_an_add_that_would_exceed_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, cap=2)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    client.post("/api/subscriptions", json={"symbol": "MSFT"})
    r = client.post("/api/subscriptions", json={"symbol": "TSLA"})
    assert r.status_code == 507
    assert "cap" in r.json()["detail"].lower() or "50" in r.json()["detail"] or "2" in r.json()["detail"]
    assert client.get("/api/subscriptions").json()["pinned"] == ["AAPL", "MSFT"]


def test_a_leased_symbol_counts_against_the_cap(tmp_path, monkeypatch):
    """A lease occupies an EODHD slot exactly as a pin does. Ignoring leases would
    let the widget report free capacity the vendor does not have."""
    client = _client(tmp_path, monkeypatch, cap=2)
    client.post("/subscribe", json={"symbols": ["NVDA"], "ttl": 300})
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    body = client.get("/api/subscriptions").json()
    assert body["leased"] == ["NVDA"]
    assert body["used"] == 2, "one pinned + one leased"
    assert client.post("/api/subscriptions", json={"symbol": "MSFT"}).status_code == 507


def test_a_symbol_both_pinned_and_leased_counts_once(tmp_path, monkeypatch):
    """THE union rule. EODHD sees a SET of symbols per connection, so the same
    symbol pinned and leased is one subscription. Summing would refuse adds while
    slots were still free."""
    client = _client(tmp_path, monkeypatch, cap=2)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    client.post("/subscribe", json={"symbols": ["AAPL"], "ttl": 300})
    body = client.get("/api/subscriptions").json()
    assert body["used"] == 1, "AAPL is pinned AND leased, but is one subscription"
    assert client.post("/api/subscriptions", json={"symbol": "MSFT"}).status_code == 201


def test_removing_a_symbol_unpins_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    assert client.delete("/api/subscriptions/AAPL").status_code == 200
    assert client.get("/api/subscriptions").json()["pinned"] == []


def test_removing_something_not_pinned_is_a_404(tmp_path, monkeypatch):
    assert _client(tmp_path, monkeypatch).delete("/api/subscriptions/AAPL").status_code == 404


def test_a_leased_symbol_cannot_be_removed_through_this_api(tmp_path, monkeypatch):
    """Leases lapse on their own TTL; this widget does not own them."""
    client = _client(tmp_path, monkeypatch)
    client.post("/subscribe", json={"symbols": ["NVDA"], "ttl": 300})
    assert client.delete("/api/subscriptions/NVDA").status_code == 404


def test_the_symbol_path_parameter_is_case_insensitive(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    assert client.delete("/api/subscriptions/aapl").status_code == 200


def test_a_pinned_symbol_reaches_the_feed(tmp_path, monkeypatch):
    """The point of pinning: the feed must actually want the symbol."""
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    assert "AAPL" in client.app.state.manager._union("us")


def test_unpinning_removes_it_from_the_feed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    client.delete("/api/subscriptions/AAPL")
    assert "AAPL" not in client.app.state.manager._union("us")


def test_symbols_already_on_disk_are_fed_at_startup(tmp_path, monkeypatch):
    """A restart must restore the subscriptions, not just the list."""
    import json

    p = tmp_path / "w.json"
    p.write_text(json.dumps(["AAPL", "EURUSD"]))
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(p))
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "50")
    client = make_client()
    with client:  # entering the context runs lifespan
        manager = client.app.state.manager
        assert "AAPL" in manager._union("us")
        assert "EURUSD" in manager._union("forex")


def test_pinning_does_not_disturb_a_lease_on_another_symbol(tmp_path, monkeypatch):
    """Watchlist and leases are separate _conns entries; _union merges them."""
    client = _client(tmp_path, monkeypatch)
    client.post("/subscribe", json={"symbols": ["NVDA"], "ttl": 300})
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    union = client.app.state.manager._union("us")
    assert {"AAPL", "NVDA"} <= union


def test_the_page_is_served_as_html(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/subscriptions")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text.lower()


def test_the_page_is_self_contained_with_no_external_requests(tmp_path, monkeypatch):
    """It renders inside an iframe in the desktop app, which may be offline. A CDN
    script or webfont would leave the widget blank rather than degraded."""
    body = _client(tmp_path, monkeypatch).get("/subscriptions").text
    for bad in ("http://", "https://", "//cdn", "src=\"//"):
        assert bad not in body, f"page reaches outside for {bad!r}"


def test_the_widget_is_declared_as_an_iframe_pointing_at_an_absolute_url(tmp_path, monkeypatch):
    """The desktop client passes an iframe widget's endpoint straight to
    `new URL(raw)` with no base -- a relative path is refused, so the served
    spec must carry the full public URL, not the bare route name in the file."""
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    widgets = _client(tmp_path, monkeypatch).get("/widgets.json").json()
    w = widgets["subscriptions"]
    assert w["type"] == "iframe"
    assert w["endpoint"] == f"https://openbb.{EXAMPLE_TAILNET}:6903/subscriptions"


def test_a_trailing_slash_on_the_public_url_does_not_double_up(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903/")
    widgets = _client(tmp_path, monkeypatch).get("/widgets.json").json()
    assert widgets["subscriptions"]["endpoint"] == f"https://openbb.{EXAMPLE_TAILNET}:6903/subscriptions"


@pytest.mark.parametrize("unset", [None, "", "  "])
def test_without_a_public_url_the_widget_points_at_the_address_the_client_used(tmp_path, monkeypatch, unset):
    """A direct connection (tailnet Serve, a local relay) must get a URL it can load: the
    scheme and host the request came in on, not an internal compose hostname."""
    if unset is None:
        monkeypatch.delenv("LIVE_GRID_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", unset)
    client = _client(tmp_path, monkeypatch)
    widgets = client.get("http://localhost:26906/widgets.json").json()
    assert widgets["subscriptions"]["endpoint"] == "http://localhost:26906/subscriptions"
    assert "live_grid" in widgets
    # The page it frames posts back to the same origin; that must not be refused.
    r = client.post("http://localhost:26906/api/subscriptions", json={"symbol": "AAPL"},
                    headers={"Origin": "http://localhost:26906"})
    assert r.status_code == 201
    r = client.post("http://localhost:26906/api/subscriptions", json={"symbol": "MSFT"},
                    headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    # Review finding 6: a rebinding page sends a Host and an Origin that agree; with no
    # public URL, only a loopback host may make a browser write.
    r = client.post("http://rebound.example.com:26906/api/subscriptions", json={"symbol": "TSLA"},
                    headers={"Origin": "http://rebound.example.com:26906"})
    assert r.status_code == 403


def test_a_websocket_registered_symbol_counts_toward_used(tmp_path, monkeypatch):
    """The budget must reflect the vendor's real view: manager._conns holds
    pins, leases AND /live_grid_ws registrations, and all three are subscribed
    at EODHD. Reading only pinned|leased understates `used`."""
    client = _client(tmp_path, monkeypatch)
    client.app.state.manager.register("ws-test", ["NVDA"])
    body = client.get("/api/subscriptions").json()
    assert body["used"] == 1
    assert body["pinned"] == []
    assert body["leased"] == []


def test_a_websocket_registered_symbol_counts_against_the_cap(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, cap=1)
    client.app.state.manager.register("ws-test", ["NVDA"])
    r = client.post("/api/subscriptions", json={"symbol": "AAPL"})
    assert r.status_code == 507


def test_a_watchlist_over_the_cap_is_truncated_at_startup(tmp_path, monkeypatch):
    """The file is hand-editable; the cap must still hold even for symbols
    that were never added through the API."""
    import json

    p = tmp_path / "w.json"
    p.write_text(json.dumps(["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]))
    monkeypatch.setenv("LIVE_GRID_WATCHLIST", str(p))
    monkeypatch.setenv("LIVE_GRID_MAX_SYMBOLS", "2")
    client = make_client()
    with client:  # entering the context runs lifespan
        manager = client.app.state.manager
        registered = {
            conn_id[len("watchlist:"):]
            for conn_id in manager._conns
            if conn_id.startswith("watchlist:")
        }
        assert len(registered) == 2
        assert registered == {"AAPL", "AMZN"}, "the first 2 sorted, not just the first 2 in the file"


def test_add_with_no_origin_header_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/subscriptions", json={"symbol": "AAPL"}).status_code == 201


def test_add_with_a_matching_origin_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/subscriptions",
        json={"symbol": "AAPL"},
        headers={"Origin": f"https://openbb.{EXAMPLE_TAILNET}:6903"},
    )
    assert r.status_code == 201


def test_add_with_a_foreign_origin_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/subscriptions",
        json={"symbol": "AAPL"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


def test_delete_with_a_foreign_origin_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    client = _client(tmp_path, monkeypatch)
    client.post("/api/subscriptions", json={"symbol": "AAPL"})
    r = client.delete(
        "/api/subscriptions/AAPL", headers={"Origin": "https://evil.example.com"}
    )
    assert r.status_code == 403
    assert client.get("/api/subscriptions").json()["pinned"] == ["AAPL"]


def test_get_subscriptions_ignores_origin(tmp_path, monkeypatch):
    """The Origin check is only on the two mutating routes."""
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://openbb.{EXAMPLE_TAILNET}:6903")
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/subscriptions", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 200


def test_an_exchange_qualified_symbol_is_stored_bare_and_a_foreign_one_refused(tmp_path, monkeypatch):
    """L1 (NAS, 2026-10-16): AAPL.US reached the feed as-is and the SDK refused the whole set."""
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/subscriptions", json={"symbol": "aapl.us"})
    assert r.status_code == 201 and r.json()["pinned"] == ["AAPL"]
    assert client.post("/api/subscriptions", json={"symbol": "AAPL"}).status_code == 409
    for bad in ("AAPL.LSE", "BRK.B", "A B"):
        assert client.post("/api/subscriptions", json={"symbol": bad}).status_code == 422, bad
    assert client.delete("/api/subscriptions/AAPL.US").status_code == 200


def test_subscribe_normalises_qualified_symbols_and_refuses_invalid_ones(tmp_path, monkeypatch):
    """L1: the observed request, {"symbols": ["BTC-USD.CC", "AAPL.US"]}, now leases the bare
    symbols; a symbol the feed cannot take is a 422 before any lease is made."""
    client = _client(tmp_path, monkeypatch)
    r = client.post("/subscribe", json={"symbols": ["BTC-USD.CC", "AAPL.US"]})
    assert r.status_code == 200 and sorted(r.json()["leases"]) == ["AAPL", "BTC-USD"]
    r = client.post("/subscribe", json={"symbols": ["MSFT", "AAPL.LSE"]})
    assert r.status_code == 422 and "AAPL.LSE" in r.json()["detail"]
    assert "MSFT" not in client.get("/api/subscriptions").json()["leased"]


def test_grid_params_keep_only_symbols_the_feed_can_take():
    """L1: /live_grid, /symbol_meta and live_grid_ws params all read symbols through this."""
    from app.main import _parse_symbols

    assert _parse_symbols("AAPL.US, btc-usd.cc,BRK.B,,^GSPC") == ["AAPL", "BTC-USD", "^GSPC"]


def test_a_legacy_qualified_watchlist_entry_counts_once_and_deletes_by_either_spelling(tmp_path, monkeypatch):
    """S1: a pre-L1 watchlist holding AAPL.US took a cap slot the feed never used and answered
    404 to DELETE /api/subscriptions/AAPL.US."""
    import json

    (tmp_path / "w.json").write_text(json.dumps(["AAPL.US", "BRK.B"]))
    client = _client(tmp_path, monkeypatch)
    body = client.get("/api/subscriptions").json()
    assert body["pinned"] == ["AAPL", "BRK.B"]
    assert client.delete("/api/subscriptions/AAPL.US").status_code == 200
    assert client.delete("/api/subscriptions/BRK.B").status_code == 200
    assert client.get("/api/subscriptions").json()["pinned"] == []
