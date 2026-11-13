# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Rita's chart tools: one MCP endpoint, `/charts/mcp`, served by the arts-charts app.

Streamable HTTP, stateless, JSON replies -- what BDOBB's MCP client speaks
(protocol 2025-06-18; no session to keep, so nothing to cap or expire). Every
tool is a thin client of this app's own REST API, reached in-process: a tool
write is validated, revision-checked and announced on /charts/events exactly
like a card's save, and a tool read computes through the routes a card reads.

Every result is one JSON text item. Titles, labels and every other value in
it are data written by users, Rita or the operator's studies -- never prose
built from them -- so a client brackets the whole item as untrusted (BDOBB
does, as for describe_table) and nothing here needs escaping.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from arts_charts.anchors import fixed_range
from arts_charts.chart_body import (MAX_SYMBOLS, indicators, series_tickers, study_groups,
                                   ticker_of, unresolved)
from arts_charts.chart_ops import OpError, apply
from arts_charts.documents import WAKE_BY
from arts_charts.snapshots import HEIGHT, WIDTH, SnapshotError, Snapshots
from arts_charts.store import Store, is_chart_id
from arts_charts.catalog import catalog
from arts_charts.ta.session import has_regular_session, is_intraday
from arts_charts.tokens import TokenError, verify
from arts_charts.watches import DEFAULT_COOLDOWN

#: list_charts and chart_history return at most this many entries, newest first.
LIST_MAX = 100
#: describe_chart's whole result is at most this many characters of JSON.
DESCRIBE_MAX = 32_000
#: The header the worker sends a wake token in (spec §2 permissions).
WAKE_HEADER = "x-arts-charts-wake"
#: What a wake may do, on its own charts only (spec §2): read, picture, annotate.
WAKE_TOOLS = frozenset({"describe_chart", "snapshot_chart", "arrange_chart"})
WAKE_OPS = frozenset({"add_anchor", "remove_anchor", "add_level", "remove_level",
                      "add_drawing", "remove_drawing"})


class Refused(ToolError):
    """A tool call that cannot be done; the client sees `isError` and this text.
    (Any other exception reaches the client as "Error executing tool <name>".)"""


@dataclass(frozen=True)
class Caller:
    """Who is calling and what they may do -- the one permission seam.

    Interactive (BDOBB relaying the user's chat, behind the stack's
    credentials): `charts` is None -- every tool on every chart, saved as
    `rita`. A wake (the worker, with a token bound to one event): `charts`
    are that event's charts, and only WAKE_TOOLS with WAKE_OPS run, saved as
    the token's `rita:watch:<id>`.
    """

    by: str = "rita"
    charts: frozenset[str] | None = None

    def check(self, tool: str, chart_id: str | None = None, ops: list | None = None) -> None:
        """Raise Refused when this caller may not run `tool` (on `chart_id`, with `ops`)."""
        if self.charts is None:
            return
        if tool not in WAKE_TOOLS:
            raise Refused(f"{tool} needs the user: a wake may only describe, snapshot or "
                          "annotate its own chart")
        if chart_id not in self.charts:
            raise Refused("this wake may not touch that chart")
        if ops is not None and not all(isinstance(op, dict) and isinstance(op.get("op"), str)
                                       and op["op"] in WAKE_OPS for op in ops):
            raise Refused("a wake may only add or remove anchors, levels and drawings")


def caller(ctx: Context) -> Caller:
    """The caller of this request, from its wake token if it carries one. A token that
    does not verify is refused outright -- never read as the user."""
    request = ctx.request_context.request
    token = request.headers.get(WAKE_HEADER) if request is not None else None
    if token is None:
        return Caller()
    try:
        claims = verify(os.environ.get("ARTS_CHARTS_SECRET"), token, "wake")
    except TokenError as exc:
        raise Refused(f"wake token refused: {exc}") from None
    by, charts = claims.get("by"), claims.get("charts")
    if not (isinstance(by, str) and WAKE_BY.fullmatch(by) and isinstance(charts, list)):
        raise Refused("wake token refused: bad claims")
    return Caller(by=by, charts=frozenset(c for c in charts if isinstance(c, str)))


def _out(value) -> str:
    return json.dumps(value)


def ticker_query(body: dict, ticker: str, today: date | None = None,
                 honour_range: bool = True) -> dict:
    """The /ta_snapshot query for one ticker's study socket: what the card asks /ta_series_ws
    for on that ticker (spec 2026-11-13 §2) -- the document's window, interval, basis and
    provider, and only the studies on that ticker. The session decision is list:1's, as the
    card sends list:1's to every socket (plan R6).

    The window is the card's own default (window.ts barsWindow): five days intraday, a year
    otherwise, ending today; `warmup=auto` pads it as the card's padStart does. A fixed saved
    range (both ends literal instants) is honoured; a relative one is not (rulings 2026-11-05):
    S14 stamps `now` with the save instant, so describe_chart and a snapshot would otherwise
    freeze on the save date. A watch passes `honour_range=False`: its window always ends today,
    so it sees each new bar.
    """
    today = date.today() if today is None else today  # the worker passes its own clock's
    interval = body["interval"]
    days = 5 if is_intraday(interval) else 365
    own = [s for s in body.get("series", [])
           if s["type"] != "study" or ticker_of(body, s.get("symbol"))[0] == ticker]
    query = {"symbol": ticker, "interval": interval, "start": str(today - timedelta(days=days)),
             "end": str(today), "indicators": indicators(own),
             "basis": "raw" if body.get("adjusted") is False else "adjusted", "warmup": "auto"}
    if "provider" in body:
        query["provider"] = body["provider"]
    # The card's path (ta/session.regular_only) filters on the same decision.
    if body.get("session") == "regular" and has_regular_session(body["symbol"], interval):
        query["session"] = "regular"
    if honour_range and (fixed := fixed_range(body)):
        query["start"], query["end"] = fixed
    return query


def compute_query(body: dict, today: date | None = None, honour_range: bool = True) -> dict:
    """list:1's query: what the card's main study socket is asked for (ticker_query)."""
    return ticker_query(body, body["symbol"], today, honour_range)


def study_queries(body: dict, today: date | None = None,
                  honour_range: bool = True) -> list[tuple[str, str, dict]]:
    """(ticker, label, query) per study socket the card opens, list:1 first (study_groups)."""
    return [(ticker, label, ticker_query(body, ticker, today, honour_range))
            for ticker, label, _ in study_groups(body)]


def readout(snapshot: dict) -> dict:
    """The last bar and each study output's latest value, from a /ta_snapshot payload, and
    the bar source's `live` (true, "partial" or false), why it is false (`live_reason`),
    whether today's volume is one venue's (`live_volume`), and whether that last bar is
    still forming (`meta.forming` names it, as the candle time spells it)."""
    candles = snapshot.get("candles") or []
    meta = snapshot.get("meta") or {}
    studies = []
    for pane in snapshot.get("panes", []):
        for series in pane.get("series", []):
            last = next((p for p in reversed(series.get("data", [])) if p.get("value") is not None),
                        {"time": None, "value": None})
            studies.append({"label": series.get("label"), "column": series.get("column"),
                            "req": series.get("req"), "time": last["time"], "value": last["value"]})
    last = candles[-1] if candles else None
    return {"last_bar": last, "studies": studies, "live": meta.get("live", False),
            "live_reason": meta.get("live_reason"), "live_volume": meta.get("live_volume"),
            "forming": last is not None and last["time"] == meta.get("forming")}


async def describe(api: httpx.AsyncClient, doc: dict) -> dict:
    """A document plus its readout, computed by /ta_snapshot -- the first frame
    /ta_series_ws sends a card -- and bounded to DESCRIBE_MAX characters."""
    query = compute_query(doc["body"])
    result = {"document": doc, "window": {"start": query["start"], "end": query["end"]}}
    skipped = unresolved({k: v for k, v in doc["body"].items() if k != "range"})
    notes = [f"{entry} has no saved instant; it is skipped until the chart is next saved in BDOBB"
             for entry in skipped]
    result["series_tickers"], unresolved_refs = series_tickers(doc["body"])
    if notes := notes + unresolved_refs:
        result["notes"] = notes
    result.update(_reading(await api.get("/ta_snapshot", params=query)))
    # Each other ticker's studies, from its own socket's query (spec 2026-11-13 §3).
    # study_groups adds a ticker after list:1 only for a study, so each entry has one.
    others = [(label, q) for _, label, q in study_queries(doc["body"])[1:]]
    if others:
        result["ticker_readouts"] = [
            {"ticker": label, **_reading(await api.get("/ta_snapshot", params=q))}
            for label, q in others]
    return _bounded(result)


def _reading(response: httpx.Response) -> dict:
    """A /ta_snapshot answer as describe reports it: the readout, or why there is none."""
    if response.status_code == 200:
        return {"readout": readout(response.json())}
    if response.status_code == 502:
        return {"readout_error": "bars unavailable"}
    return {"readout_error": response.json().get("detail", f"HTTP {response.status_code}")}


def _bounded(result: dict) -> dict:
    """Drop the bulk a model cannot use -- drawings, levels, the panels text, then
    trailing study outputs -- until the result fits, saying how much went."""
    if len(_out(result)) <= DESCRIBE_MAX:
        return result
    body = result["document"]["body"]
    omitted = {k: len(body[k]) for k in ("drawings", "levels", "anchors", "panels") if k in body}
    body = {k: v for k, v in body.items() if k not in omitted}
    styled = [s for s in body.get("series", []) if "style" in s]
    if styled:
        omitted["series_styles"] = len(styled)
        body["series"] = [{k: v for k, v in s.items() if k != "style"} for s in body["series"]]
    result["document"]["body"] = body
    result["omitted"] = omitted
    studies = result.get("readout", {}).get("studies", [])
    while studies and len(_out(result)) > DESCRIBE_MAX:
        studies.pop()
        omitted["studies"] = omitted.get("studies", 0) + 1
    for entry in reversed(result.get("ticker_readouts", [])):
        studies = entry.get("readout", {}).get("studies", [])
        while studies and len(_out(result)) > DESCRIBE_MAX:
            studies.pop()
            omitted["studies"] = omitted.get("studies", 0) + 1
    if len(_out(result)) > DESCRIBE_MAX:
        # Whatever is left (a long title, 64 series) is still too big: identity only.
        doc = result["document"]
        omitted["body"] = len(body)
        result["document"] = {k: doc[k] for k in ("id", "title", "revision") if k in doc}
        result["document"]["body"] = {k: body[k] for k in ("symbol", "interval") if k in body}
    return result


def _study_menu() -> str:
    """The legal studies, generated from the registry /ta_registry lists -- not a second list."""
    return "; ".join(
        f"{e['name']}({', '.join(f'{p['name']}={p['default']}' for p in e['params'])})"
        f" [{'overlay' if e['pane'] == 'price' else 'own pane'}]"
        for e in catalog())


def _id(chart_id: str) -> str:
    """`chart_id` as a path segment: only an id, never `events` (the feed's route, a stream
    the in-process client would wait on forever), a `..` or a query."""
    if not is_chart_id(chart_id):
        raise Refused("no such chart (or no such revision)")
    return chart_id


async def _json(response: httpx.Response, *ok: int,
                missing: str = "no such chart (or no such revision)"):
    """The JSON of a response whose status is in `ok`, else Refused with the API's reason."""
    if response.status_code in ok:
        return response.json()
    if response.status_code == 404:
        raise Refused(missing)
    try:
        detail = response.json().get("detail", "")
    except ValueError:
        detail = ""
    raise Refused(f"refused ({response.status_code}): {detail}" if detail
                  else f"arts-charts answered {response.status_code}")


#: The schema of an arts_chart_snapshot artifact's content (v12 part 3).
SNAPSHOT_SCHEMA = "arts-chart-snapshot/1"


def snapshot_artifact(doc: dict, shot: dict, meta: dict) -> dict:
    """The agent-rita artifact item for a kept snapshot (v12 part 3 R1-R3): ids and
    numbers only -- the client fetches the PNG by the two ids, never by a URL."""
    body = doc["body"]
    return {"$rita_kind": "artifact", "artifact": {
        "type": "arts_chart_snapshot", "uuid": shot["id"],
        "name": f"{body['symbol']} · {body['interval']}",
        "description": f"Art's Charts snapshot, revision {shot['revision']}",
        "content": {"schema": SNAPSHOT_SCHEMA, "chart_id": doc["id"], "snapshot_id": shot["id"],
                    "revision": shot["revision"], "width": meta["width"],
                    "height": meta["height"], "created_at": shot["created_at"],
                    "title": doc["title"], "symbol": body["symbol"],
                    "interval": body["interval"]}}}


def chart_mcp(api: httpx.AsyncClient, snapshots: Snapshots, store: Store) -> MCPServer:
    """The chart tools over `api`, an httpx client on this app's own routes; `store` keeps
    the PNGs snapshot_chart renders for a chat."""
    tools = MCPServer("arts-charts", instructions=(
        "Art's Charts chart documents. Call describe_chart before changing a chart and pass "
        "its revision as expected_revision; a 'stale' status means someone saved first -- "
        "describe again and redo the change on what is there now."))
    menu = _study_menu()

    async def save(method: str, path: str, by: str, revision: int, payload=None) -> str:
        response = await api.request(method, path, json=payload,
                                     headers={"If-Match": str(revision), "X-Updated-By": by})
        if response.status_code == 409:
            return _out({"status": "stale", "document": response.json()})
        return _out({"status": "saved", "document": await _json(response, 200)})

    @tools.tool(structured_output=False, description=(
        "List the chart library: id, title, symbol, interval, revision of each chart, newest "
        "change first. `search` keeps charts whose title or symbol contains it (any case)."))
    async def list_charts(ctx: Context, search: str | None = None) -> str:
        caller(ctx).check("list_charts")
        charts = await _json(await api.get("/charts"), 200)
        if search:
            needle = search.casefold()
            charts = [c for c in charts
                      if needle in c["title"].casefold() or needle in c["symbol"].casefold()]
        keep = ("id", "title", "symbol", "interval", "revision", "updated_by", "updated_at")
        return _out({"charts": [{k: c[k] for k in keep} for c in charts[:LIST_MAX]],
                     "more": max(0, len(charts) - LIST_MAX)})

    @tools.tool(structured_output=False, description=(
        "A chart document and a readout of what its card shows: the last bar and each study "
        "output's latest value, computed exactly as the card's are, over `window`; `live` says "
        "whether today's bars are the live tick plane's (true, \"partial\" after a live-grid "
        "restart, false: history only), `live_reason` why it is false (not_covered: not on "
        "the live watchlist; unavailable: the live plane cannot be reached; no_session: today "
        "is not a session this chart shows live), `live_volume` \"venue\" when today's volume "
        "counts one trading venue's trades only (far below earlier days' consolidated volume, "
        "never a collapse in trading) and `forming` whether the last bar is still forming. Series "
        "are listed in document.body.series; a series' index there is its `series` in "
        "arrange_chart. Bulky fields are left out (and counted in `omitted`) when large."))
    async def describe_chart(ctx: Context, chart_id: str) -> str:
        caller(ctx).check("describe_chart", _id(chart_id))
        return _out(await describe(api, await _json(await api.get(f"/charts/{chart_id}"), 200)))

    @tools.tool(structured_output=False, description=(
        "Render a chart as its card draws it and return the PNG's link (a path on this "
        "server) with the numbers the picture shows -- the same readout as describe_chart. "
        "In a chat the picture is also shown to the user, beside your answer. "
        f"width {WIDTH} and height {HEIGHT} by default."))
    async def snapshot_chart(ctx: Context, chart_id: str, width: int = WIDTH,
                             height: int = HEIGHT) -> list[str]:
        who = caller(ctx)
        who.check("snapshot_chart", _id(chart_id))
        # One read: the picture and the numbers are of the same revision.
        doc = await _json(await api.get(f"/charts/{chart_id}"), 200)
        try:
            png, meta = await snapshots.render(chart_id, width, height, doc=doc)
        except SnapshotError as exc:
            raise Refused(exc.reason) from None
        described = await describe(api, doc)
        described.pop("document")
        if who.charts is not None:
            # A wake (R7): today's one item, nothing kept -- its reply goes to a push, where
            # "already shown in the chat" would be false; the worker attaches its own PNGs.
            return [_out({"link": f"/charts/{chart_id}/snapshot.png?width={width}&height={height}",
                          **meta, "bytes": len(png), **described})]
        shot = await asyncio.to_thread(store.add_chart_snapshot, chart_id, meta["revision"], png)
        return [_out(snapshot_artifact(doc, shot, meta)),
                _out({"link": f"/charts/{chart_id}/snapshots/{shot['id']}.png",
                      **meta, "bytes": len(png), **described})]

    @tools.tool(structured_output=False, description=(
        "Create a chart in the library and return it. `symbol` is one ticker, or a comma list of "
        "up to 5 as the card's symbol box takes it (AAPL,MSFT): the first is the chart's symbol and "
        "its studies follow it unless a study names a symbol: a ticker, $ymbol or list:<n>. "
        "`studies` is a list of "
        "{name, params?, symbol?, panel?, side?, color?, style?}; an overlay goes on the price panel, "
        f"an own-pane study in the last panel, unless panel/side are given. Studies: {menu}"))
    async def create_chart(ctx: Context, symbol: str, interval: str,
                           studies: list[dict] | None = None, title: str | None = None) -> str:
        who = caller(ctx)
        who.check("create_chart")
        # The text the card's symbol box takes (spec 2026-11-13 §4): a ticker or a comma list.
        symbols = [t.strip().upper() for t in symbol.split(",") if t.strip()] or [""]
        if len(symbols) > MAX_SYMBOLS:
            raise Refused(f"a chart holds at most {MAX_SYMBOLS} symbols")
        body = {"schema": "chart/1", "symbol": symbols[0], "interval": interval,
                **({"symbols": symbols} if len(symbols) > 1 else {})}
        if studies:
            if not all(isinstance(s, dict) for s in studies):
                raise Refused("studies must be a list of objects")
            try:
                body, _ = apply(body, [{**s, "op": "add_study"} for s in studies])
            except OpError as exc:
                raise Refused(str(exc).replace("ops[", "studies[")) from None
        response = await api.post("/charts", json={"title": title or symbols[0], "body": body},
                                  headers={"X-Updated-By": who.by})
        return _out({"status": "saved", "document": await _json(response, 201)})

    @tools.tool(structured_output=False, description=(
        "Change a chart as one revision: every op applies or none does. expected_revision is "
        "the revision you described; if the chart moved since, nothing is written and the "
        "current document comes back with status 'stale'. Ops (chart-ops/1): "
        "{op:'set_interval', interval}; {op:'set_range', from, to} (ISO-8601 instants, e.g. "
        "2026-10-01T13:30:00Z; never an expression); {op:'clear_range'}; {op:'add_study', name, params?, symbol?, panel?, side?, "
        "color?, style?}; {op:'remove_study', series}; {op:'retune_study', series, params?, "
        "symbol?, color?, style?} (params merge; null removes a key); {op:'add_anchor', anchor} (an ISO-8601 instant or OBS-n); "
        "{op:'remove_anchor', anchor}; {op:'add_level', price}; {op:'remove_level', index}; "
        "{op:'add_drawing', drawing}; {op:'remove_drawing', index}; {op:'set_title', title}. "
        "`series` is a series id or its index in describe_chart's series list. "
        "A study's time parameter (avwap anchor) is an ISO-8601 instant or OBS-n. "
        "A study's symbol is a ticker, $ymbol, $group:<Name> or list:<n> (the chart's n-th "
        "symbol); omitted, it follows list:1; null in retune_study removes it. "
        f"Studies: {menu}"))
    async def arrange_chart(ctx: Context, chart_id: str, expected_revision: int,
                            ops: list[dict]) -> str:
        who = caller(ctx)
        who.check("arrange_chart", _id(chart_id), ops)
        doc = await _json(await api.get(f"/charts/{chart_id}"), 200)
        if doc["revision"] != expected_revision:
            return _out({"status": "stale", "document": doc})
        try:
            body, title = apply(doc["body"], ops)
        except OpError as exc:
            raise Refused(str(exc)) from None
        return await save("PUT", f"/charts/{chart_id}", who.by, expected_revision,
                          {"title": doc["title"] if title is None else title, "body": body})

    @tools.tool(structured_output=False, description=(
        f"A chart's revisions, newest first (at most {LIST_MAX}): revision, title, who saved "
        "it and when. `total` counts them all."))
    async def chart_history(ctx: Context, chart_id: str) -> str:
        caller(ctx).check("chart_history", _id(chart_id))
        revisions = await _json(await api.get(f"/charts/{chart_id}/history"), 200)
        return _out({"revisions": revisions[:LIST_MAX], "total": len(revisions)})

    @tools.tool(structured_output=False, description=(
        "Write an old revision of a chart again as its newest. expected_revision is the "
        "chart's current revision; if it moved, nothing is written and the current document "
        "comes back with status 'stale'."))
    async def restore_chart(ctx: Context, chart_id: str, revision: int,
                            expected_revision: int) -> str:
        who = caller(ctx)
        who.check("restore_chart", _id(chart_id))
        return await save("POST", f"/charts/{chart_id}/restore/{revision}", who.by,
                          expected_revision)

    def _watch(watch_id: str) -> str:
        if not is_chart_id(watch_id):
            raise Refused("no such watch")
        return watch_id

    @tools.tool(structured_output=False, description=(
        "Watch a chart. At each completed bar where `condition` holds, you are woken with "
        "`note`, the values and the chart, and your reply goes to the user's inbox and phone. "
        "condition is '<series> <op> <value|series>'. A series is close, high, low, volume, or "
        "a study on the chart as name(params in registry order)[.output]: rsi(14), "
        "bbands(20,2).bb_up; without an output, a study's first line (AVWAP cannot be watched yet: "
        "no tick source). "
        "A series may name its ticker first -- close(list:2), rsi(MSFT, 14), sma(list:2, 50) -- "
        "a ticker, $ymbol or list:<n> (not a $group:); without one it is list:1, and the two "
        "sides may name different tickers, read at the same bar. Ops: "
        "> < crosses_above crosses_below. cooldown: seconds after a firing before the next "
        f"one (default {DEFAULT_COOLDOWN}). Checked against the chart when saved."))
    async def create_watch(ctx: Context, chart_id: str, condition: str, note: str = "",
                           cooldown: int = DEFAULT_COOLDOWN) -> str:
        caller(ctx).check("create_watch", _id(chart_id))
        response = await api.post("/watches", headers={"X-Updated-By": "rita"}, json={
            "chart_id": chart_id, "condition": condition, "note": note, "cooldown": cooldown})
        watch = await _json(response, 201, missing="no such chart")
        return _out({"status": "saved", "watch": watch})

    @tools.tool(structured_output=False, description=(
        "Change a watch: any of condition, note, cooldown, enabled. The condition is checked "
        "against the chart again, and a watch in state 'erroring' is reset to 'ok'."))
    async def update_watch(ctx: Context, watch_id: str, condition: str | None = None,
                           note: str | None = None, cooldown: int | None = None,
                           enabled: bool | None = None) -> str:
        caller(ctx).check("update_watch")
        changes = {k: v for k, v in {"condition": condition, "note": note, "cooldown": cooldown,
                                     "enabled": enabled}.items() if v is not None}
        response = await api.patch(f"/watches/{_watch(watch_id)}", json=changes,
                                   headers={"X-Updated-By": "rita"})
        watch = await _json(response, 200, missing="no such watch")
        return _out({"status": "saved", "watch": watch})

    @tools.tool(structured_output=False, description="Delete a watch.")
    async def delete_watch(ctx: Context, watch_id: str) -> str:
        caller(ctx).check("delete_watch")
        response = await api.delete(f"/watches/{_watch(watch_id)}",
                                    headers={"X-Updated-By": "rita"})
        if response.status_code != 204:
            await _json(response, 204, missing="no such watch")
        return _out({"status": "deleted", "watch_id": watch_id})

    @tools.tool(structured_output=False, description=(
        "The watches (of one chart): condition, note, cooldown, enabled, muted_until, state "
        "('ok' or 'erroring', with `error` saying why) and the last bar evaluated."))
    async def list_watches(ctx: Context, chart_id: str | None = None) -> str:
        caller(ctx).check("list_watches")
        params = {"chart_id": _id(chart_id)} if chart_id is not None else {}
        return _out(await _json(await api.get("/watches", params=params), 200))

    def _schedule(schedule_id: str) -> str:
        if not is_chart_id(schedule_id):
            raise Refused("no such schedule")
        return schedule_id

    @tools.tool(structured_output=False, description=(
        "Schedule a report on up to 8 charts. At each occurrence of `when` you are woken with "
        "`note` and describe_chart of each chart, and your reply goes to the user's inbox with "
        "a snapshot of each chart, and to their phone. when is New York time: 'daily HH:MM', "
        "'weekdays HH:MM' or 'sessions HH:MM' (trading days), 24-hour. A report more than an "
        "hour late (the server was down) is skipped with a notice."))
    async def create_schedule(ctx: Context, chart_ids: list[str], when: str, note: str = "",
                              enabled: bool = True) -> str:
        caller(ctx).check("create_schedule")
        response = await api.post("/schedules", headers={"X-Updated-By": "rita"}, json={
            "chart_ids": chart_ids, "when": when, "note": note, "enabled": enabled})
        schedule = await _json(response, 201, missing="no such chart")
        return _out({"status": "saved", "schedule": schedule})

    @tools.tool(structured_output=False, description=(
        "Change a schedule: any of chart_ids, when, note, enabled. A new `when`, or enabling it "
        "again, counts from now: an occurrence already past does not run."))
    async def update_schedule(ctx: Context, schedule_id: str, chart_ids: list[str] | None = None,
                              when: str | None = None, note: str | None = None,
                              enabled: bool | None = None) -> str:
        caller(ctx).check("update_schedule")
        changes = {k: v for k, v in {"chart_ids": chart_ids, "when": when, "note": note,
                                     "enabled": enabled}.items() if v is not None}
        response = await api.patch(f"/schedules/{_schedule(schedule_id)}", json=changes,
                                   headers={"X-Updated-By": "rita"})
        schedule = await _json(response, 200, missing="no such schedule (or chart)")
        return _out({"status": "saved", "schedule": schedule})

    @tools.tool(structured_output=False, description="Delete a schedule.")
    async def delete_schedule(ctx: Context, schedule_id: str) -> str:
        caller(ctx).check("delete_schedule")
        response = await api.delete(f"/schedules/{_schedule(schedule_id)}",
                                    headers={"X-Updated-By": "rita"})
        if response.status_code != 204:
            await _json(response, 204, missing="no such schedule")
        return _out({"status": "deleted", "schedule_id": schedule_id})

    @tools.tool(structured_output=False, description=(
        "The schedules: chart_ids, when, note, enabled, and armed_at (occurrences before it "
        "do not run)."))
    async def list_schedules(ctx: Context) -> str:
        caller(ctx).check("list_schedules")
        return _out(await _json(await api.get("/schedules"), 200))

    return tools
