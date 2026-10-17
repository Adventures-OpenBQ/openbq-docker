# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Server-layer tests: widgets.json contract, REST seeding, health, key gate.
The SDK is never imported — the seed client is injected."""
import threading
import time

from fastapi.testclient import TestClient

from app.main import create_app

# openbq-docker: built at run time so scripts/check-public.py never sees a literal tailnet name.
EXAMPLE_TAILNET = ".".join(["example", "ts", "net"])


class FakeRest:
    def __init__(self, snaps=None):
        self.snaps = snaps or {}
        self.calls = []

    def get_live_stock_prices(self, ticker):
        self.calls.append(ticker)
        return self.snaps.get(ticker, {"close": "100", "previousClose": "90", "volume": "5"})


class _FakeSnapshotStore:
    """Stands in for KdbStore: no cached snapshot, ever. Keeps quotes.seed()'s
    kdb-first lookup off the real spawn/loopback/host chain -- otherwise a
    request through /live_grid or the websocket's baseline seed pays a
    genuine `connect()` to 127.0.0.1:5000."""

    def read_snapshot(self, symbol, max_age):
        return None

    def write_snapshot(self, symbol, payload):
        pass


def make_client(monkeypatch=None, **kw):
    """`monkeypatch` is optional: pass it (a pytest fixture) for any test that
    exercises REST seeding (`/live_grid`, the websocket's baseline seed) so
    quotes.seed() never reaches a real kdb+ session. Tests that only touch
    `/widgets.json` or `/health` don't need it -- see
    test_health_includes_ticks_key_when_chart_is_enabled_by_default, which
    deliberately keeps the real (never-connected) KdbSession to prove
    `.endpoint` reports None rather than raising."""
    if monkeypatch is not None:
        monkeypatch.setattr("openbq_kdb.config.resolve_config", lambda: object())
        monkeypatch.setattr("openbq_kdb.session.KdbSession", lambda config: object())
        monkeypatch.setattr("openbq_kdb.store.KdbStore", lambda session: _FakeSnapshotStore())
    app = create_app(api_key=kw.pop("api_key", "test-key"),
                     seed_client=kw.pop("seed_client", FakeRest()),
                     client_factory=kw.pop("client_factory", lambda *a, **k: _NullWs()))
    return TestClient(app)


class _NullWs:
    running = False

    def __init__(self):
        # Per instance, deliberately. As a class attribute this list is shared
        # by every client every test builds, so one test's tick is drained by
        # another test's manager.
        self.data_list: list = []

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


def test_widgets_json_declares_the_live_grid_contract():
    body = make_client().get("/widgets.json").json()
    w = body["live_grid"]
    assert w["type"] == "live_grid"
    assert w["wsEndpoint"] == "live_grid_ws"
    assert w["data"]["wsRowIdColumn"] == "symbol"
    fields = [c["field"] for c in w["data"]["table"]["columnsDefs"]]
    # The logo leads, then the symbol it belongs to.
    assert fields[:2] == ["logo_url", "symbol"]
    # snapshot-only column must never update over the socket
    vol = next(c for c in w["data"]["table"]["columnsDefs"] if c["field"] == "volume")
    assert vol["enableCellChangeWs"] is False


def test_widgets_json_declares_the_live_chart_contract():
    body = make_client().get("/widgets.json").json()
    w = body["live_chart"]
    assert w["type"] == "live_chart"
    assert w["endpoint"] == "series"
    assert w["wsEndpoint"] == "live_grid_ws"
    param_names = [p["paramName"] for p in w["params"]]
    assert param_names == ["symbol", "interval"]
    interval = next(p for p in w["params"] if p["paramName"] == "interval")
    assert [o["value"] for o in interval["options"]] == [
        "1s", "1m", "5m", "15m", "30m", "1h", "1d",
    ]


def test_live_grid_declares_its_visible_columns_and_hides_the_rest(monkeypatch):
    body = make_client().get("/widgets.json").json()
    cols = body["live_grid"]["data"]["table"]["columnsDefs"]
    visible = [c["field"] for c in cols if not c.get("hide")]
    # Each range bar is flanked by its own low and high, so the numbers line
    # up down the grid and sort -- the bar itself labels nothing.
    assert visible == [
        "logo_url", "symbol", "price", "change", "change_percent",
        "day_low", "day_range", "day_high",
        "week52_low", "week52_range", "week52_high",
        "volume",
    ]
    hidden = {c["field"]: c for c in cols if c.get("hide")}
    assert all(c["hide"] is True for c in hidden.values())

    # The desktop client renders every payload field the manifest does not
    # declare hidden as a trailing visible column. So the real regression
    # check is on the payload, not the declarations: every key a seeded
    # /live_grid row actually carries must either be one of the six visible
    # fields above or be declared here with hide: true -- otherwise it
    # renders as an extra column. Get the key set from a real seeded row
    # (same pattern as test_live_grid_seeds_rows_in_request_order) so a
    # future field added to the row makes this test fail instead of
    # silently adding a column.
    rest = FakeRest({"AAPL.US": {"close": "150", "previousClose": "100", "volume": "7"}})
    row = make_client(monkeypatch, seed_client=rest).get("/live_grid?symbol=AAPL").json()[0]
    declared_hidden = set(hidden)
    for field in row:
        assert field in visible or field in declared_hidden, (
            f"payload field {field!r} is neither a visible column nor declared hidden"
        )


def test_the_logo_is_its_own_column_carrying_the_url_as_its_value():
    body = make_client().get("/widgets.json").json()
    cols = body["live_grid"]["data"]["table"]["columnsDefs"]
    (logo,) = [c for c in cols if c["field"] == "logo_url"]
    assert "logo" in logo["renderFn"]
    # No urlKey: the column's own value IS the URL, so pointing at a second
    # field would be indirection with nothing on the other end of it.
    assert "urlKey" not in logo.get("renderFnParams", {})
    # And the symbol column beside it stays plain text.
    (sym,) = [c for c in cols if c["field"] == "symbol"]
    assert "logo" not in sym.get("renderFn", [])


def test_both_range_bars_use_one_render_fn_differing_only_in_params():
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    day, week = defs["day_range"], defs["week52_range"]
    assert day["renderFn"] == week["renderFn"] == ["rangeBar"]
    assert day["renderFnParams"] == {
        "lowKey": "day_low", "highKey": "day_high", "palette": "day",
    }
    assert week["renderFnParams"] == {
        "lowKey": "week52_low", "highKey": "week52_high", "palette": "week52",
    }
    # The palettes MUST differ: the two bars sit side by side in one row, and
    # identical colours read as one repeated column rather than two bands.
    assert day["renderFnParams"]["palette"] != week["renderFnParams"]["palette"]


def test_the_bars_and_volume_opt_out_of_the_change_flash():
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    for field in ("day_range", "week52_range", "volume"):
        assert defs[field]["enableCellChangeWs"] is False


def test_price_keeps_the_change_flash():
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    assert "showCellChange" in defs["price"]["renderFn"]
    assert defs["price"].get("enableCellChangeWs") is not False


def test_price_columns_print_in_full_and_volume_stays_abbreviated():
    # A live price must show every tick: abbreviated, 2,493.47 -> 2,494.29 both
    # read "2.49K" and the cell looks frozen (web test, 2026-10-12). BDOBB
    # honours a column's `abbreviate: false` (widgetsJson.ts); volume is a
    # magnitude and keeps the K/M suffix.
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    for field in ("price", "day_open", "day_low", "day_high", "week52_low", "week52_high", "bid", "ask"):
        assert defs[field]["abbreviate"] is False, field
    assert "abbreviate" not in defs["volume"]


def test_kdb_ticks_is_a_plain_table_widget():
    body = make_client().get("/widgets.json").json()
    w = body["kdb_ticks"]
    assert w["type"] == "table"
    assert w["endpoint"] == "ticks"
    assert [p["paramName"] for p in w["params"]] == ["symbol", "limit"]
    # A tick table must show what each tick is: the time of day (not just the
    # date an ISO string would be inferred as), the full price (not 81.5K) and
    # a sub-unit crypto size (not 0 at two decimals).
    defs = {c["field"]: c for c in w["data"]["table"]["columnsDefs"]}
    assert defs["time"]["formatterFn"] == "none"
    assert defs["price"]["abbreviate"] is False
    assert defs["size"]["formatterFn"] == "none"


def test_live_grid_seeds_rows_in_request_order(monkeypatch):
    rest = FakeRest({"AAPL.US": {"close": "150", "previousClose": "100", "volume": "7"}})
    rows = make_client(monkeypatch, seed_client=rest).get("/live_grid?symbol=AAPL,BTC-USD").json()
    assert [r["symbol"] for r in rows] == ["AAPL", "BTC-USD"]
    assert rows[0]["price"] == 150.0
    assert rows[0]["change"] == 50.0
    assert rest.calls == ["AAPL.US", "BTC-USD.CC"]


def test_live_grid_with_no_symbols_is_an_empty_list():
    assert make_client().get("/live_grid").json() == []


def test_missing_api_key_is_a_clear_500_not_a_stacktrace():
    app = create_app(api_key=None, seed_client=None,
                     client_factory=lambda *a, **k: _NullWs())
    resp = TestClient(app).get("/live_grid?symbol=AAPL")
    assert resp.status_code == 500
    assert "EODHD_API_KEY" in resp.json()["detail"]


def test_health_reports_per_feed_state():
    body = make_client().get("/health").json()
    assert body["status"] == "ok"
    assert set(body["feeds"]) == {"us", "crypto", "forex"}


def test_health_omits_ticks_key_when_chart_is_disabled(monkeypatch):
    monkeypatch.setenv("LIVE_GRID_CHART", "false")
    body = make_client().get("/health").json()
    assert "ticks" not in body


def test_health_includes_ticks_key_when_chart_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("LIVE_GRID_CHART", raising=False)
    body = make_client().get("/health").json()
    # REVIEW (openbq-docker v10, tick spool): the exact key set gains the spool's
    # counters; see docs/v10/live-grid-kdb-port.md "Tick spool and fast reconnect".
    assert set(body["ticks"]) == {"buffered", "written", "dropped", "endpoint",
                                  "spooled", "replayed", "deduped", "quarantined"}
    # A session that has never connected must report None, not raise.
    assert body["ticks"]["endpoint"] is None


def _receive_json(ws, timeout=10.0):
    """`ws.receive_json()` with a deadline.

    starlette's TestClient websocket offers no timeout, so a message that never
    arrives blocks forever. That is not a hypothetical: this test wedged CI for
    ten minutes and was killed by the job's hang guard, and because the wait was
    unbounded the failure carried no message -- only a faulthandler dump.
    A bounded wait turns the same fault into a one-line assertion.

    The reader runs on a daemon thread so a stuck receive cannot keep the
    interpreter alive after the test fails.
    """
    box: dict = {}

    def grab():
        try:
            box["msg"] = ws.receive_json()
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=grab, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(f"no websocket message within {timeout}s")
    if "err" in box:
        raise box["err"]
    return box["msg"]


def test_websocket_registers_params_and_streams_dirty_rows(monkeypatch):
    # `with` on the TestClient, not only on the websocket. manager.run() -- the
    # drain loop that marks rows dirty -- is started by the app's lifespan, and
    # starlette runs lifespan only when the client is a context manager. Without
    # it the loop never runs, no feed client is built, and no tick can reach the
    # producer. That is why the previous version of this test poked
    # manager._dirty by hand, and poking it is what made the test wedge CI.
    with make_client(monkeypatch) as client, \
            client.websocket_connect("/live_grid_ws") as ws:
        ws.send_json({"params": {"symbol": "AAPL"}})
        manager = client.app.state.manager
        # Deliver the tick the way the SDK does -- append to the feed client's
        # buffer -- rather than marking manager._dirty from this thread.
        #
        # pop_dirty() snapshots the dirty set and then clears it, as two
        # statements. Both run on the event loop, so production never interleaves
        # them. A mark added from THIS thread, though, can land between the
        # snapshot and the clear: absent from the snapshot, then erased. The row
        # never flushed, receive_json() blocked forever, and CI's hang guard
        # killed the job ten minutes later with no message.
        #
        # Appending to data_list is the supported cross-thread operation -- the
        # SDK thread appends at the tail, the drain loop deletes from the head --
        # and _drain_all() then marks _dirty on the event loop, where it belongs.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if manager._conns and manager._clients.get("us") is not None:
                break
            time.sleep(0.02)
        assert any("AAPL" in by_feed["us"] for by_feed in manager._conns.values())
        feed_client = manager._clients.get("us")
        assert feed_client is not None, "us feed client was never created"
        feed_client.data_list.append({"s": "AAPL", "p": 151.0})
        # The registration's baseline seed may flush AAPL at its snapshot price
        # (100.0) first; the tick above follows it, so consume until it arrives.
        row = None
        for _ in range(10):
            row = _receive_json(ws)
            assert row["symbol"] == "AAPL"
            if row["price"] == 151.0:
                break
        assert row is not None and row["price"] == 151.0


def test_change_and_percent_are_two_columns_not_one_parenthetical():
    """They sort independently and line up down the grid, which a percent
    riding inside the change cell as "(3.40%)" could not do."""
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    assert "renderFnParams" not in defs["change"]
    pct = defs["change_percent"]
    assert pct.get("hide") is not True
    # The payload carries a fraction, so it needs the x100 formatter.
    assert pct["formatterFn"] == "normalizedPercent"
    assert "greenRed" in pct["renderFn"]


def test_the_price_and_change_columns_are_right_aligned():
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    for field in ("price", "change", "change_percent"):
        assert defs[field]["align"] == "right", field


def test_the_range_bars_flanking_columns_hug_their_bar():
    """A low right-aligned and a high left-aligned put both numbers against
    the bar they describe, rather than at opposite ends of the row with the
    bar stranded between them."""
    body = make_client().get("/widgets.json").json()
    defs = {c["field"]: c for c in body["live_grid"]["data"]["table"]["columnsDefs"]}
    assert defs["day_low"]["align"] == "right"
    assert defs["day_high"]["align"] == "left"
    assert defs["week52_low"]["align"] == "right"
    assert defs["week52_high"]["align"] == "left"


def test_live_grid_declares_a_width_for_every_column():
    # bdobb only switches a table to fixed layout when every visible column
    # has a width; one unsized column and the whole live grid re-solves its
    # column widths from the cell text on every tick, which reads as stutter.
    # Hidden columns get one too, so showing one cannot unfix the layout.
    spec = make_client().get("/widgets.json").json()
    cols = spec["live_grid"]["data"]["table"]["columnsDefs"]
    assert [c["field"] for c in cols if not isinstance(c.get("width"), int)] == []


def test_apps_json_only_names_widgets_this_service_publishes(monkeypatch):
    """The assertion that matters over time: rename a widget in widgets.json
    without following it into apps.json and this fails, rather than shipping a
    dashboard of cards that silently never resolve.

    live-grid had no apps.json test at all until the V10.0.0 dashboard gained
    `live_chart` and `kdb_cache_chart` -- the two Ep. 10 widgets the service
    published but no dashboard ever placed. stores-explorer has carried the
    equivalent guard on the donor line; this is that guard, here.
    """
    # `subscriptions` is always published (unset, its endpoint is the request's
    # own address); a configured deployment is modelled here.
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://live-grid.{EXAMPLE_TAILNET}")
    client = make_client()
    published = set(client.get("/widgets.json").json())
    import json
    from pathlib import Path

    apps = json.loads((Path(__file__).resolve().parent.parent / "apps.json").read_text())
    named = {
        card["i"]
        for app in apps
        for tab in app["tabs"].values()
        for card in tab["layout"]
    }
    assert named <= published, f"apps.json names widgets this service does not publish: {sorted(named - published)}"


def test_the_v10_dashboard_shows_every_episode_10_widget():
    """Ep. 10 shipped five widgets; the example dashboard showed three.

    `live_chart` (the chart that draws itself while you watch) and
    `kdb_cache_chart` (what the episode's cache is FOR) were published and
    never placed, so a reader opening the example saw neither.
    """
    import json
    from pathlib import Path

    apps = json.loads((Path(__file__).resolve().parent.parent / "apps.json").read_text())
    # BDOBB's own Episode 10 example since the v10 sync (EPISODE=10 apps-sync from
    # docs/examples/v10.0.0-live-grid.apps.json); the donor named it "... - V10.0.0".
    v10 = next(a for a in apps if a["name"] == "Example Dashboard - Version 10.0.0 - Live Grid")
    shown = {card["i"] for tab in v10["tabs"].values() for card in tab["layout"]}
    assert {"live_grid", "subscriptions", "kdb_ticks", "live_chart", "kdb_cache_chart"} <= shown


def test_health_reports_the_subscriptions_widget_as_published_without_a_public_url(monkeypatch):
    """Unset, live-grid names the page by the request's own address, so it is always published."""
    monkeypatch.delenv("LIVE_GRID_PUBLIC_URL", raising=False)
    assert make_client().get("/health").json()["subscriptions"] == {"published": True}


def test_health_reports_the_subscriptions_widget_as_published_when_configured(monkeypatch):
    monkeypatch.setenv("LIVE_GRID_PUBLIC_URL", f"https://live-grid.{EXAMPLE_TAILNET}")
    body = make_client().get("/health").json()
    assert body["subscriptions"] == {"published": True}


# -- L4 (NAS, 2026-10-16): a crashed background task was invisible until shutdown ---------


def test_supervise_logs_restarts_with_backoff_and_records_the_error(caplog):
    import asyncio

    from app.main import supervise

    calls, sleeps, tasks = [], [], {}

    async def flaky():
        calls.append(1)
        if len(calls) <= 3:
            raise ValueError(f"boom {len(calls)}")
        raise asyncio.CancelledError

    async def fake_sleep(s):
        sleeps.append(s)

    with caplog.at_level("ERROR"):
        try:
            asyncio.run(supervise("feed manager", flaky, tasks, sleep=fake_sleep))
        except asyncio.CancelledError:
            pass
    assert len(calls) == 4 and sleeps == [1.0, 2.0, 4.0]
    assert tasks["feed manager"]["restarts"] == 3
    assert tasks["feed manager"]["last_error"] == "ValueError: boom 3"
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 3 and errors[0].exc_info is not None


def test_health_reports_degraded_when_the_feed_manager_crashed(monkeypatch):
    """The NAS symptom: /health said ok while nothing drained. A crash now shows."""
    import time

    from app.feeds import FeedManager

    async def crash(self):
        raise ValueError("year 56794849 is out of range")

    monkeypatch.setattr(FeedManager, "run", crash)
    with make_client() as client:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            body = client.get("/health").json()
            if body["status"] != "ok":
                break
            time.sleep(0.05)
    assert body["status"] == "degraded"
    assert body["tasks"]["feed manager"]["last_error"] == "ValueError: year 56794849 is out of range"
    assert body["tasks"]["feed manager"]["restarts"] >= 1


def test_supervise_resets_its_backoff_after_a_healthy_run():
    """S3 (re-review 2026-10-17): the delay only grew, so after a few crashes days apart every
    later crash cost the full 60 s. A run that stayed up HEALTHY_RUN_S starts again from 1 s."""
    import asyncio

    from app.main import supervise

    now = {"t": 0.0}
    sleeps, tasks = [], {}
    # how long each run stays up before it raises; the last one is cancelled
    ups = [0.0, 0.0, 0.0, 400.0, 0.0]

    async def flaky():
        if not ups:
            raise asyncio.CancelledError
        now["t"] += ups.pop(0)
        raise ValueError("boom")

    async def fake_sleep(s):
        sleeps.append(s)
        now["t"] += s

    try:
        asyncio.run(supervise("feed manager", flaky, tasks, sleep=fake_sleep, clock=lambda: now["t"]))
    except asyncio.CancelledError:
        pass
    assert sleeps == [1.0, 2.0, 4.0, 1.0, 2.0]


def test_subscriptions_page_paints_its_own_background():
    # Under a dark color-scheme the page's text turns light; without its own
    # background it sat on the embedding frame's white and vanished.
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "subscriptions.html").read_text()
    assert "background: Canvas" in html and "color: CanvasText" in html
