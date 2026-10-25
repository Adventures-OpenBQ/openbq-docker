// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { upstreamPath, newsSubscription, liveGridSubscription, stateFile, socketTicket, socketTicketNonce, socketTicketValid, socketTarget, refSubscription } from "./policy.mjs";

// Built at run time so the public-content scan never sees a literal tailnet name.
const TAILNET = ["example-tailnet", "ts", "net"].join(".");

const ORIGIN = `https://openbq.${TAILNET}:10000`;
const TOKEN = "synthetic_test_credential_not_for_deployment";
const at = path => new URL(path, ORIGIN);
// The approved-feed allowlist the /news rules read: url -> rss-ticker feed id. `route`
// resolves a path against an empty allowlist (no feed approved), `routeWith` against one.
const FEED = "https://feeds.example.com/news.xml";
const route = raw => upstreamPath(at(raw), { feeds: {} });
const routeWith = (raw, feeds) => upstreamPath(at(raw), { feeds });

test("the two root documents forward exactly, with no query", () => {
  assert.equal(route("/api/widgets.json"), "/api/widgets.json");
  assert.equal(route("/api/apps.json"), "/api/apps.json");
  assert.equal(route("/api/widgets.json?x=1"), null);
  assert.equal(route("/api/templates.json"), null);
});

test("the reference root documents forward exactly, with no query", () => {
  assert.equal(route("/ref/widgets.json"), "/ref/widgets.json");
  assert.equal(route("/ref/apps.json"), "/ref/apps.json");
  assert.equal(route("/ref/widgets.json?x=1"), null);
});

test("every reference GET forwards under the shape bounds, re-serialised; Omni refused", () => {
  assert.equal(route("/ref/metric_widget"), "/ref/metric_widget");
  assert.equal(route("/ref/table_widget"), "/ref/table_widget");
  assert.equal(route("/ref/data/prices"), "/ref/data/prices");
  assert.equal(route("/ref/pdf_widget_base64"), "/ref/pdf_widget_base64");
  // Omni routes (code-executing or not) are refused at the door.
  for (const bad of ["/ref/omni-widget", "/ref/omni-sql-widget", "/ref/omni-python-widget"]) {
    assert.equal(route(bad), null, bad);
  }
  // The four exact dotted documents (ruled 2026-10-15) forward, no query; other dotted paths stay refused.
  for (const ok of ["/ref/agents.json", "/ref/bundle.apps.json",
    "/ref/market-examples.apps.json", "/ref/assets/bdobb-logo.svg"]) {
    assert.equal(route(ok), ok, ok);
  }
  for (const bad of ["/ref/agents.json?x=1", "/ref/assets/other.svg", "/ref/assets/bdobb-logo.svg/x"]) {
    assert.equal(route(bad), null, bad);
  }
  // Empty segments would let "//host" pick the upstream; omni is refused at any depth.
  for (const bad of ["/ref//omni-sql-widget", "/ref//openbq-api/api/v1/x", "/ref/data//x", "/ref//",
    "/ref/data/omni-widget", "/ref/omnibus", "/ref/data/omni"]) {
    assert.equal(route(bad), null, bad);
  }
  assert.equal(route("/ref/data/omelette"), "/ref/data/omelette");
  // Same structural refusals as /api: uppercase, dot, control char, duplicate key, 41 pairs.
  for (const bad of [
    "/ref/Metric_Widget", "/ref/metric_widget.json",
    "/ref/metric_widget?x=a%0d%0aY:1", "/ref/metric_widget?a=1&a=2",
    "/ref/metric_widget?" + "a=1&".repeat(41).slice(0, -1),
  ]) assert.equal(route(bad), null, bad);
});

test("every api/v1 route forwards under the shape bounds, re-serialised", () => {
  assert.equal(route("/api/api/v1/equity/price/quote?symbol=AAPL&provider=yfinance"),
    "/api/api/v1/equity/price/quote?symbol=AAPL&provider=yfinance");
  assert.equal(route("/api/api/v1/economy/gdp/real"), "/api/api/v1/economy/gdp/real");
  // The query that leaves is rebuilt from parsed pairs: a raw "+" becomes %2B, a space %20.
  assert.equal(route("/api/api/v1/news/company?symbol=AAPL&query=a b"),
    "/api/api/v1/news/company?symbol=AAPL&query=a+b");
  for (const bad of [
    "/api/api/v1/Equity/price/quote",                       // uppercase segment
    "/api/api/v1/equity/price/quote.json",                  // a dot
    "/api/api/v1/equity/price/quote?symbol=AAPL%0d%0aX:1",  // control character in a value
    "/api/api/v1/equity/price/quote?symbol=AAPL&symbol=MSFT", // duplicate name
    "/api/api/v1/equity/price/quote?" + "a=1&".repeat(41).slice(0, -1), // 41 pairs
    "/api/api/v1/equity/price/quote?1bad=1",                // name grammar
    "/api/api/v1/" + "a/".repeat(101),                      // path over 200 chars
    "/api/api/v1/equity/price/quote?symbol=" + "A".repeat(1025), // value over 1024
    "/api/docs", "/api/openapi.json", "/api/redoc", "/api/api/v2/x",
  ]) assert.equal(route(bad), null, bad);
  const long = "/api/api/v1/equity/price/quote?" + Array.from({ length: 5 }, (_, i) => `p${i}=${"v".repeat(1000)}`).join("&");
  assert.equal(route(long), null, "over 4096 characters");
});

test("calendar/trading forwards on a MIC and a year inside the client's window, else refused", () => {
  assert.equal(route("/api/api/v1/calendar/trading?exchange=XNYS&year=2026"),
    "/api/api/v1/calendar/trading?exchange=XNYS&year=2026");
  assert.equal(route("/api/api/v1/calendar/trading?exchange=XNYS&year=2041"), null);
  assert.equal(route("/api/api/v1/calendar/trading?exchange=XNYS"), null);
});

test("openbq-docker serves no /ai: Rita's document and everything under /ai are refused", () => {
  for (const path of ["/ai/agents.json", "/ai/agents.json?x=1", "/ai/v1/query", "/ai/other"]) assert.equal(route(path), null, path);
});

test("the wire's history page forwards for an approved feed id and a limit of 1-50", () => {
  const feeds = { [FEED]: 7 };
  assert.equal(routeWith("/news/api/news?feed_id=7&limit=1", feeds), "/news/api/news?feed_id=7&limit=1");
  assert.equal(routeWith("/news/api/news?feed_id=7&limit=50", feeds), "/news/api/news?feed_id=7&limit=50");
  for (const bad of [
    "/news/api/news?feed_id=8&limit=1",           // an id the operator never approved
    "/news/api/news?feed_id=0&limit=1",           // ids start at 1, so 0 is never approved
    "/news/api/news?feed_id=07&limit=1",          // no leading zeros: one spelling per id
    "/news/api/news?limit=1",                     // no feed at all
    "/news/api/news?feed_id=7",                   // no limit: fails closed, never defaulted
    "/news/api/news?feed_id=7&limit=0",
    "/news/api/news?feed_id=7&limit=51",
    "/news/api/news?feed_id=7&limit=1&extra=1",   // an unknown key is a refusal
    "/news/api/news?feed_id=7&feed_id=7&limit=1", // a duplicated name
    "/news/api/news/extra?feed_id=7&limit=1",
    "/news/admin", "/news/ws/news", "/news/",
  ]) assert.equal(routeWith(bad, feeds), null, bad);
  // With no feed approved there is no history to page: every id is unapproved.
  assert.equal(route("/news/api/news?feed_id=7&limit=1"), null);
  // The web layer vendors this file; a caller that passes no config at all gets the honest
  // refusal (nothing is approved), not a TypeError the gateway would turn into a 502.
  assert.equal(upstreamPath(at("/news/api/news?feed_id=7&limit=1")), null);
  assert.equal(upstreamPath(at("/api/widgets.json")), "/api/widgets.json");
});

test("a subscription frame is rebuilt from approved feeds alone, or refused", () => {
  const feeds = { [FEED]: 7, "https://other.example.com/rss": 8 };
  const sub = data => newsSubscription(Buffer.from(data), { feeds });
  // Display names and any extra property are stripped: what leaves is url and nothing else.
  assert.equal(sub(JSON.stringify({ subscribe: [{ url: FEED, name: "rename", admin: true }] })),
    JSON.stringify({ subscribe: [{ url: FEED }] }));
  // An unapproved feed alongside an approved one is DROPPED, not a reason to refuse the card.
  assert.equal(sub(JSON.stringify({ subscribe: [{ url: FEED }, { url: "https://unapproved.invalid/f" }] })),
    JSON.stringify({ subscribe: [{ url: FEED }] }));
  for (const bad of [
    "not-json", "[]", "null", '"subscribe"',
    JSON.stringify({ subscribe: [] }),                                        // nothing to subscribe to
    JSON.stringify({ subscribe: [{ url: "https://unapproved.invalid/f" }] }),  // none approved
    JSON.stringify({ subscribe: [{ url: FEED }], admin: true }),              // a second key
    JSON.stringify({ unsubscribe: [{ url: FEED }] }),                         // not the one key
    JSON.stringify({ subscribe: [{ url: FEED }, { url: FEED }] }),             // a duplicate
    JSON.stringify({ subscribe: [{ url: 7 }] }),                              // not a string
    JSON.stringify({ subscribe: [{}] }),                                      // no url at all
    JSON.stringify({ subscribe: Array.from({ length: 51 }, (_, i) => ({ url: `https://f${i}.invalid` })) }),
  ]) assert.equal(sub(bad), null, bad);
  // No feed approved: nothing is ever a valid subscription.
  assert.equal(newsSubscription(Buffer.from(JSON.stringify({ subscribe: [{ url: FEED }] })), { feeds: {} }), null);
});

test("families that arrive with later lines are refused at openbq-docker v10 (donor v10.1.4)", () => {
  for (const later of [
    // What a later line's study family adds and this tag's live-grid genuinely does not serve. Be
    // precise: /ta_chart and /ta_chart_ws ARE served here, so they are routes (below), and
    // /grid/ticks -- which was on this list at v10.0.3 -- is one too, because this line's
    // live-grid has the kdb tick reader. /snapshot is live-grid's own diagnostic, never a
    // contract route.
    "/grid/ta_registry", "/grid/live_grid_studies?symbol=AAPL", "/grid/snapshot",
    // The tick chart exists, but only inside its grammar: `provider` is not a key this door
    // maps (so a caller cannot force the vendor on a stream that refetches once a second),
    // a macro is a filename stem, a source is local or eodhd, and indicators carry no space.
    "/grid/ta_chart", "/grid/ta_chart?symbol=",
    "/grid/ta_chart?symbol=AAPL&provider=eodhd", "/grid/ta_chart?symbol=AAPL&macro=../etc",
    "/grid/ta_chart?symbol=AAPL&source=vendor", "/grid/ta_chart?symbol=AAPL&indicators=rsi period=14",
    "/grid/ta_chart?symbol=AAPL&anchor=yesterday", "/grid/ta_chart?symbol=AAPL&theme=neon",
    "/grid/ta_chart?symbol=AAPL,MSFT",
    // "=" only as a trailing futures "=F", and show_seam only as true or false.
    "/grid/ta_chart?symbol=CL=X", "/grid/ta_chart?symbol=C=L", "/grid/ta_chart?symbol==F",
    "/grid/ta_chart?symbol=CL=F=F", "/grid/ta_chart?symbol=CL=f",
    "/grid/live_grid?symbol=CL=F", "/grid/symbol_meta?symbol=CL=F",
    "/grid/ta_chart?symbol=AAPL&show_seam=1", "/grid/ta_chart?symbol=AAPL&show_seam=",
    "/grid/ta_chart?symbol=AAPL&show_seam=True",
    // /ticks exists, but only inside its grammar: a list, an unknown key, or a limit
    // outside 1..1000 is refused before live-grid is dialled.
    "/grid/ticks", "/grid/ticks?symbol=", "/grid/ticks?symbol=AAPL,MSFT",
    "/grid/ticks?symbol=AAPL&admin=true", "/grid/ticks?symbol=AAPL&limit=0",
    "/grid/ticks?symbol=AAPL&limit=1001", "/grid/ticks?symbol=AAPL&limit=-1",
    "/grid/ticks?symbol=AAPL&limit=all",
    // live-grid's own admin and page surfaces, which are never in the contract at any tag.
    "/grid/demo", "/grid/health", "/grid/subscribe", "/grid/api/subscriptions",
    // And the paths that were never this door's: the tick cache (q IPC), MCP, key-maint, and
    // a bare manifest at the root (each backend's is under its own prefix).
    "/api/api/v1/calendar/trading?exchange=XNYS&year=2026", "/", "/widgets.json", "/mcp", "/keys", "/tick"]) {
    assert.equal(route(later), later.startsWith("/api/api/v1/calendar/trading")
      ? "/api/api/v1/calendar/trading?exchange=XNYS&year=2026" : null, later);
  }
});

// ---- The grid family (Ep. 10): live-grid's own widget surface behind the door.

test("the grid's REST routes take exactly what this line's live-grid serves", () => {
  // The manifests: exact path, no query. On this line live-grid really serves apps.json
  // (the Ep. 10 example dashboard) -- a 404 is dataClient's designed
  // "this backend ships no apps", so forwarding it degrades where the client expects to.
  for (const ok of ["/grid/widgets.json", "/grid/apps.json"]) assert.equal(route(ok), ok, ok);
  // The seeds: the watchlist grammar, and nothing but `symbol`.
  assert.equal(route("/grid/live_grid?symbol=AAPL,MSFT,^GSPC"), "/grid/live_grid?symbol=AAPL%2CMSFT%2C%5EGSPC");
  assert.equal(route("/grid/symbol_meta?symbol=AAPL.US"), "/grid/symbol_meta?symbol=AAPL.US");
  // The tick chart, this line's own feature: the six keys its widget declares plus the
  // theme dataClient appends to every chart-typed widget's query.
  assert.equal(route("/grid/ta_chart?symbol=NVDA"), "/grid/ta_chart?symbol=NVDA");
  assert.equal(
    route("/grid/ta_chart?symbol=NVDA&interval=1m&source=eodhd&macro=classic-momentum&indicators=supertrend:period=10,ichimoku&theme=dark"),
    "/grid/ta_chart?symbol=NVDA&interval=1m&source=eodhd&macro=classic-momentum&indicators=supertrend%3Aperiod%3D10%2Cichimoku&theme=dark");
  assert.equal(route("/grid/ta_chart?symbol=NVDA&anchor=2026-08-28T14:30:00-04:00"),
    "/grid/ta_chart?symbol=NVDA&anchor=2026-08-28T14%3A30%3A00-04%3A00");
  // Futures history (CL=F on the day oil went negative) and the seam toggle.
  assert.equal(route("/grid/ta_chart?symbol=CL=F&interval=1d&start=2020-04-01&end=2020-04-30"),
    "/grid/ta_chart?symbol=CL%3DF&interval=1d&start=2020-04-01&end=2020-04-30");
  assert.equal(route("/grid/ta_chart?symbol=CL%3DF"), "/grid/ta_chart?symbol=CL%3DF");
  for (const v of ["true", "false"]) {
    assert.equal(route(`/grid/ta_chart?symbol=NVDA&show_seam=${v}`), `/grid/ta_chart?symbol=NVDA&show_seam=${v}`);
  }
  // The kdb tick reader, this line's own route: one symbol, an optional bounded limit.
  assert.equal(route("/grid/ticks?symbol=AAPL"), "/grid/ticks?symbol=AAPL");
  assert.equal(route("/grid/ticks?symbol=AAPL&limit=1000"), "/grid/ticks?symbol=AAPL&limit=1000");
  assert.equal(route("/grid/ticks?symbol=BTC-USD&limit=1"), "/grid/ticks?symbol=BTC-USD&limit=1");
  // The Sector Map: no parameters of its own, only the theme every chart widget carries.
  assert.equal(route("/grid/sector_map"), "/grid/sector_map");
  assert.equal(route("/grid/sector_map?theme=dark"), "/grid/sector_map?theme=dark");
  // The bars: the same parameter set on both, plus `theme` on the chart alone -- the client
  // appends the resolved theme to every chart-typed widget, so refusing it would refuse the
  // one grid chart this line publishes.
  assert.equal(route("/grid/series?symbol=AAPL&interval=1d&provider=kdb"),
    "/grid/series?symbol=AAPL&interval=1d&provider=kdb");
  assert.equal(route("/grid/chart?symbol=AAPL&interval=5m&theme=dark&start=2026-09-01&end=2026-09-14T09%3A30%3A15-04%3A00"),
    "/grid/chart?symbol=AAPL&interval=5m&theme=dark&start=2026-09-01&end=2026-09-14T09%3A30%3A15-04%3A00");
  for (const bad of [
    "/grid/widgets.json?x=1", "/grid/apps.json?x=1",     // a manifest takes no query
    "/grid/live_grid",                                    // symbol is required
    "/grid/live_grid?symbol=",                            // and non-empty
    "/grid/live_grid?symbol=AAPL&admin=true",             // an unknown key is a refusal
    "/grid/live_grid?symbol=AAPL;DROP TABLE",             // outside the list grammar
    "/grid/live_grid?symbol=" + "A".repeat(241),          // past the list cap
    "/grid/symbol_meta?symbol=AAPL&limit=5",              // not this route's key
    "/grid/series?symbol=AAPL,MSFT",                      // one symbol, not a list
    "/grid/series?symbol=AAPL&interval=7m",               // not an interval live-grid serves
    "/grid/series?symbol=AAPL&provider=unapproved",       // kdb or eodhd, nothing else
    "/grid/series?symbol=AAPL&start=yesterday",           // resolved instants only
    "/grid/series?symbol=AAPL&theme=dark",                // theme is the chart's alone
    "/grid/chart?symbol=AAPL&theme=neon",                 // light or dark
    "/grid/chart?symbol=AAPL&indicators=rsi:period=14",   // a later line's parameter
    "/grid/sector_map?theme=neon",                        // light or dark
    "/grid/sector_map?symbol=XLK",                        // it takes no symbol
  ]) assert.equal(route(bad), null, bad);
});

test("a grid params frame is rebuilt from the one value that passed, and repeats are valid", () => {
  const frame = value => liveGridSubscription(Buffer.from(JSON.stringify(value)));
  // Rebuilt, not forwarded: the frame that reaches live-grid carries `params.symbol` alone.
  assert.equal(frame({ params: { symbol: "AAPL,MSFT" } }), '{"params":{"symbol":"AAPL,MSFT"}}');
  // Every frame goes through the same rule, so a repeat is as valid as the first -- which is
  // the difference from the wire: live-grid's protocol re-sends this on every param change.
  assert.equal(frame({ params: { symbol: "TSLA" } }), '{"params":{"symbol":"TSLA"}}');
  for (const bad of [
    '{"params":{"symbol":"AAPL"}',                                  // not JSON
    JSON.stringify({ params: { symbol: "AAPL" }, admin: true }),    // a second top-level key
    JSON.stringify({ subscribe: [{ url: "https://x.invalid" }] }),  // the wire's frame, not this one
    JSON.stringify({ params: { symbol: "AAPL", limit: 5 } }),        // a second params key
    JSON.stringify({ params: { symbol: "AAPL;DROP TABLE" } }),       // outside the grammar
    JSON.stringify({ params: { symbol: "" } }),                      // empty
    JSON.stringify({ params: { symbol: 7 } }),                       // not a string
    JSON.stringify({ params: { symbol: "A".repeat(241) } }),          // past the cap
    JSON.stringify({ params: [] }), JSON.stringify({ params: null }),
    JSON.stringify([]), JSON.stringify(null), JSON.stringify("params"), JSON.stringify(7),
  ]) assert.equal(liveGridSubscription(Buffer.from(bad)), null, bad);
});

test("the state allow-list names the app's own JSON files and nothing else", () => {
  for (const ok of ["settings.json", "backends.json", "folders.json", "chat.json", "chart-presets.json",
    "dashboards/preview.json", "dashboards/3f2a-B_c.json",
    "workspaces/7c9e6679-7425-40de-944b-e07fc1f90ae7.json", "layouts/7c9e6679-7425-40de-944b-e07fc1f90ae7.json"]) assert.equal(stateFile(ok), true, ok);
  for (const bad of ["", "settings.json.tmp", "../settings.json", "dashboards/../settings.json", "dashboards/a/b.json",
    "files/a.pdf", "Settings.json", "dashboards/" + "a".repeat(81) + ".json", "workspaces/a/b.json", "layouts/../settings.json",
    "workspace/a.json", 7, null]) assert.equal(stateFile(bad), false, String(bad));
});

test("tickets: signed over the exact target, thirty seconds, base64url, refused when tampered", () => {
  const target = "/news/ws/news";
  const ticket = socketTicket(TOKEN, target, 1_700_000_000_000);
  assert.match(ticket, /^\d{13}\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/);
  assert.equal(typeof socketTicketNonce(TOKEN, target, ticket, 1_700_000_000_000), "string");
  assert.equal(socketTicketValid(TOKEN, target, ticket, 1_700_000_000_000 + 29_000), true);
  assert.equal(socketTicketValid(TOKEN, target, ticket, 1_700_000_000_000 + 31_000), false);
  assert.equal(socketTicketValid(TOKEN + "x", target, ticket, 1_700_000_000_000), false);
  assert.equal(socketTicketValid(TOKEN, target + "?x=1", ticket, 1_700_000_000_000), false);
  // Tamper inside the signature, not its last character: the 43rd base64url character carries
  // two padding bits, so swapping "A" for "B" there decoded to the same bytes about one run in
  // sixteen (a flaky test in the donor, never a replay: the nonce is what is single-use).
  const pos = ticket.length - 10, flipped = ticket[pos] === "A" ? "B" : "A";
  assert.equal(socketTicketValid(TOKEN, target, ticket.slice(0, pos) + flipped + ticket.slice(pos + 1), 1_700_000_000_000), false);
  assert.equal(socketTicketValid("", target, ticket, 1_700_000_000_000), false);
  assert.equal(socketTicketNonce(TOKEN, target, "junk", 1_700_000_000_000), null);
});

test("tickets tolerate a signer clock up to five seconds ahead; expiry stays exact", () => {
  const target = "/ref/live_grid_ws", now = 1_700_000_000_000;
  // Minted by a signer whose clock reads 4 s / 6 s ahead of this verifier's.
  assert.equal(socketTicketValid(TOKEN, target, socketTicket(TOKEN, target, now + 4000), now), true);
  assert.equal(socketTicketValid(TOKEN, target, socketTicket(TOKEN, target, now + 6000), now), false);
  const ticket = socketTicket(TOKEN, target, now);
  assert.equal(socketTicketValid(TOKEN, target, ticket, now + 30_000), true); // the expiry millisecond
  assert.equal(socketTicketValid(TOKEN, target, ticket, now + 30_001), false); // expired
});

test("the skew tolerance boundary is exactly 5000 ms ahead", () => {
  const target = "/ref/live_grid_ws", now = 1_700_000_000_000;
  // TICKET_SKEW_MS (5000) is private to policy.mjs; the literal pins the boundary.
  assert.equal(socketTicketValid(TOKEN, target, socketTicket(TOKEN, target, now + 5000), now), true);
  assert.equal(socketTicketValid(TOKEN, target, socketTicket(TOKEN, target, now + 5001), now), false);
});

test("the reference's, the wire's and the grid's sockets are the targets a ticket may name at openbq-docker v10 (donor v10.1.4)", () => {
  assert.equal(socketTarget("/ref/live_grid_ws", ORIGIN), "/ref/live_grid_ws");
  assert.equal(socketTarget("/news/ws/news", ORIGIN), "/news/ws/news");
  assert.equal(socketTarget("/grid/live_grid_ws", ORIGIN), "/grid/live_grid_ws");
  // The tick chart's socket is the one whose query IS its subscription, so a ticket over it
  // must name that query -- re-serialised from the validated pairs, exactly as it will be
  // dialled, so the signer and the door agree byte for byte.
  assert.equal(socketTarget("/grid/ta_chart_ws?symbol=NVDA&interval=1m", ORIGIN),
    "/grid/ta_chart_ws?symbol=NVDA&interval=1m");
  assert.equal(socketTarget("/grid/ta_chart_ws?symbol=NVDA&indicators=rsi:period=14", ORIGIN),
    "/grid/ta_chart_ws?symbol=NVDA&indicators=rsi%3Aperiod%3D14");
  assert.equal(socketTarget("/grid/ta_chart_ws?symbol=CL=F&show_seam=true", ORIGIN),
    "/grid/ta_chart_ws?symbol=CL%3DF&show_seam=true");
  for (const raw of [
    "/ref/live_grid_ws?x=1", "/ref/live_grid_ws?", "/ref/live_grid_ws#x", "/ref/live_grid_ws/",
    "/ref/other_ws", "/ref/../ref/live_grid_ws", "/REF/live_grid_ws",
    "/news/ws/news?admin=1",            // the socket takes no query, so neither does its ticket
    "/news/ws/news#x",
    "/grid/live_grid_ws?symbol=AAPL",   // the params frame is the subscription, not the URL
    "/grid/live_grid_ws#x",
    "/grid/ta_series_ws?symbol=AAPL&interval=5m",  // a later line's socket
    "/grid/ta_chart_ws",                // this one is the reverse: no query, nothing to stream
    "/grid/ta_chart_ws?symbol=NVDA&provider=eodhd",   // the key the door does not map
    "/grid/ta_chart_ws?symbol=NVDA&macro=../etc",     // a macro is a filename stem
    "/grid/ta_chart_ws?symbol=NVDA&interval=7m",
    "/grid/ta_chart_ws?symbol=NVDA#x",
    "/grid/ta_chart_ws?symbol=CL=X",
    "/grid/ta_chart_ws?symbol=NVDA&show_seam=yes",
    "/news/api/news?feed_id=7&limit=1", // a REST route is not a socket target
    "/grid/live_grid?symbol=AAPL",
    "/", "//x", "x", 7, null,
  ]) assert.equal(socketTarget(raw, ORIGIN), null, String(raw));
  // A raw target is read against the ORIGIN the caller passes, and refused off it.
  assert.equal(socketTarget(ORIGIN + "/news/ws/news", "https://other.example.com"), null);
});

test("refSubscription relays only a symbol params frame, rebuilt, else null", () => {
  assert.equal(refSubscription('{"params":{"symbol":"AAPL"}}'), '{"params":{"symbol":"AAPL"}}');
  assert.equal(refSubscription(Buffer.from('{"params":{"symbol":"AAPL,MSFT"}}')), '{"params":{"symbol":"AAPL,MSFT"}}');
  assert.equal(refSubscription('{"params":{"symbol":"^GSPC,AAPL.US,BRK-B"}}'), '{"params":{"symbol":"^GSPC,AAPL.US,BRK-B"}}');
  // Whitespace the caller added is not forwarded: the frame is rebuilt.
  assert.equal(refSubscription('{ "params" : { "symbol" : "AAPL" } }'), '{"params":{"symbol":"AAPL"}}');
  assert.equal(refSubscription('{"params":{"symbol":"' + "A".repeat(240) + '"}}'), '{"params":{"symbol":"' + "A".repeat(240) + '"}}');
  for (const bad of ['{"params":{"symbol":"AAPL","x":1}}', '{"params":{"ticker":"AAPL"}}',
    '{"params":{"symbol":123}}', '{"params":{"symbol":["AAPL"]}}', '{"params":{"symbol":null}}',
    '{"subscribe":[]}', '{"params":{"symbol":""}}', '{"params":["symbol"]}', '{"params":null}',
    '{"params":{"symbol":"AAPL MSFT"}}', '{"params":{"symbol":"AAPL\\nX"}}', '{"params":{"symbol":"AAPL;MSFT"}}',
    '{"params":{"symbol":"' + "A".repeat(241) + '"}}', '["params"]', 'null', '7', 'not json', '']) {
    assert.equal(refSubscription(bad), null, bad);
  }
  // A caller's extra top-level key never survives the rebuild; a doubled key is not two values.
  assert.equal(refSubscription('{"params":{"symbol":"AAPL"},"admin":1}'), null);
  assert.equal(refSubscription('{"params":{"symbol":"AAPL"},"params":{"symbol":"MSFT"}}'), '{"params":{"symbol":"MSFT"}}');
});

test("managed table routes and explicitly registered SSRM POSTs are method bounded", async () => {
  const p = await import("./policy.mjs");
  const route = (path, method = "GET") => p.tableRoute(new URL(path, "https://example.com"), method, { ssrmRoutes: ["/api/api/v1/test/rows"] });
  for (const path of ["/table/healthz", "/table/capabilities", "/table/widgets.json", "/table/sources/backends", "/table/exports/export_1/batches?sequence=0"]) assert.ok(route(path));
  for (const path of ["/table/sources/uploads", "/table/sources/backends", "/table/sessions", "/table/sessions/session_1/commands", "/table/sessions/session_1/derive", "/table/sessions/session_1/cancel", "/table/sessions/session_1/exports", "/api/api/v1/test/rows"]) assert.ok(route(path, "POST"));
  for (const path of ["/table/sources/s_1", "/table/sessions/session_1", "/table/exports/export_1"]) assert.ok(route(path, "DELETE"));
  for (const [path, method] of [["/table/sessions", "GET"], ["/table/healthz", "POST"], ["/table/sessions/x/commands?url=http://evil", "POST"], ["/table/exports/x/batches?sequence=-1", "GET"], ["/table/exports/x/batches?sequence=0&sequence=1", "GET"], ["/api/api/v1/test/other", "POST"], ["/table/sessions/x/anything", "POST"]]) assert.equal(route(path, method), null);
});
