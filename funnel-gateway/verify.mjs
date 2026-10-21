// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { pathToFileURL } from "node:url";
import { WebSocket } from "ws";
import { readConfig } from "./config.mjs";

/**
 * Proves the lock without opening anything: every probe is either refused or answers the
 * gateway's own health document. `base` is where the gateway is reached -- the container's
 * own loopback by default, or the public door (GATEWAY_URL=https://openbq.<tailnet>.ts.net:10000)
 * once Serve publishes it. The Host header is always the configured origin's, so a probe
 * through the door proves Serve preserved it. The last probes are WebSocket upgrades on this
 * tag's THREE socket routes: for each, the lock, the Origin rule, and then the route itself.
 *
 * TWO of them are probed to 101: the wire (or 503 when the operator has approved no feeds)
 * and the quote grid (or 503 when settings.json does not turn on the `live` profile's
 * live-grid -- openbq-docker v10). Both open upstream only on a first frame, and this gate sends
 * none, so a 101 there opens and closes the door's own socket and nothing else -- no upstream
 * connection is made, no feed is polled and no symbol is subscribed.
 *
 * The tick chart's socket is deliberately NOT probed to 101, and that asymmetry is the point.
 * /grid/ta_chart_ws dials live-grid AT UPGRADE (its query is its subscription, so there is no
 * frame to wait for) and live-grid's handler runs build_series immediately -- an openbb-api
 * historical call that can reach a paid vendor. A 101 probe would therefore make the upstream
 * call this whole gate promises not to make. So that route is probed with REFUSALS only: no parameters, an unknown key, and an
 * out-of-grammar subscription -- each rejected by the route rules before anything is dialled.
 * Its 101 is covered by the door's own suite (gateway.test.mjs), where the upstream is a
 * fixture rather than live-grid. THE GUARANTEE HOLDS: this gate makes no upstream call at all.
 */
export async function verify(config, base = "http://127.0.0.1:8091") {
  const host = new URL(config.origin).host;
  const good = { Host: host, Authorization: `Bearer ${config.token}` };
  const send = new URL(base).protocol === "https:" ? httpsRequest : httpRequest;
  function status(path, headers = {}) {
    return new Promise((resolve, reject) => {
      const req = send(new URL(path, base), { headers: { Host: host, ...headers }, timeout: 5000 },
        res => { res.resume(); resolve(res.statusCode); });
      req.on("timeout", () => req.destroy(new Error("Timeout")));
      req.on("error", reject); req.end();
    });
  }
  // The upgrade path goes through the same door and the same two gates, so it is probed
  // through the same `base`: ws:// over the loopback, wss:// once GATEWAY_URL is the Funnel
  // origin -- a handshake Serve mishandles shows up here and nowhere else.
  const socketBase = base.replace(/^http/, "ws");
  function wsStatus(headers, route = "/news/ws/news") {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(new URL(route, socketBase), {
        headers: { Host: host, ...headers }, handshakeTimeout: 5000,
      });
      ws.on("error", reject);
      ws.on("unexpected-response", (_, res) => { res.resume(); resolve(res.statusCode); ws.terminate(); });
      ws.on("open", () => { resolve(101); ws.close(); });
    });
  }
  const expect = (actual, expected, what) => {
    if (actual !== expected) throw new Error(`Gateway verification failed: ${what} answered ${actual}, wanted ${expected}`);
  };
  // No provider calls: every path below is refused before any upstream is dialled.
  for (const path of ["/", "/_gateway/health", "/api/api/v1/equity/price/quote?symbol=AAPL&provider=yfinance",
    "/api/widgets.json", "/state/1", "/ai/v1/query", "/news/api/news?feed_id=1&limit=1", "/news/ws/news",
    "/grid/widgets.json", "/grid/live_grid?symbol=AAPL", "/grid/live_grid_ws",
    "/grid/ta_chart?symbol=AAPL", "/grid/ta_chart_ws?symbol=AAPL",
    // The watchlist API is behind the lock like every other route. The Subscriptions PAGE
    // (/grid/subscriptions, exact, no query) is the one route served without the token --
    // a frame cannot send one -- and it is not probed to 200 here, because its first answer
    // fetches the page from live-grid and this gate dials nothing. Its exception is proved
    // NARROW instead: the same path with a query, or a trailing slash, is still locked.
    "/grid/api/subscriptions", "/grid/api/subscriptions/AAPL",
    "/grid/subscriptions?x=1", "/grid/subscriptions/",
    "/tick", "/mcp", "/keys", "/widgets.json"]) {
    expect(await status(path), 401, `${path} without a token`);
  }
  expect(await status("/_gateway/health", { Authorization: "Bearer invalid" }), 401, "a wrong token");
  expect(await status("/_gateway/health", good), 200, "health through the lock");
  expect(await status("/_gateway/health", { ...good, Host: "untrusted.invalid" }), 421, "a foreign Host");
  expect(await status("/_gateway/health", { ...good, Origin: "https://untrusted.invalid" }), 403, "a foreign Origin");
  for (const path of ["/", "/tick", "/mcp", "/keys", "/widgets.json",
    // The grid's own shape rules, each refused before live-grid is dialled. First the paths
    // that are not in the contract at all: live-grid's admin and page surfaces, its lease
    // route, and the study routes a later line adds, which this tag's live-grid genuinely does NOT serve. Its
    // watchlist API IS a route since V10-P5 (server.mjs subscriptionRoute), so only its
    // out-of-grammar shapes appear: a query, a nested path, and a GET on one symbol. Be precise about which those are: /ta_chart and /ta_chart_ws ARE served here
    // (live-grid/app/main.py), so they are routes, not refusals -- what remains absent is
    // the rest of that study family, /ta_registry, /live_grid_studies and /ta_series_ws.
    // /grid/ticks is a route here too (this line's kdb tick reader), so for all three only
    // their out-of-grammar shapes appear below. The kdb+ tick cache ITSELF is not here at
    // all and never will be: q IPC executes arbitrary code with no auth.
    "/grid/demo", "/grid/health", "/grid/subscribe",
    "/grid/api/subscriptions?x=1", "/grid/api/subscriptions/A/B", "/grid/api/subscriptions/AAPL",
    "/grid/subscriptions?x=1",
    "/grid/snapshot", "/grid/ta_registry", "/grid/live_grid_studies?symbol=AAPL",
    "/grid/ta_series_ws",
    "/grid/ticks", "/grid/ticks?symbol=AAPL,MSFT", "/grid/ticks?symbol=AAPL&limit=1001",
    "/grid/ta_chart", "/grid/ta_chart?symbol=AAPL&provider=eodhd",
    "/grid/ta_chart?symbol=AAPL&macro=../etc", "/grid/ta_chart?symbol=AAPL&source=vendor",
    // Then the parameter rules on the routes that ARE in it: an unknown key is a refusal
    // rather than a passthrough, a manifest takes no query at all, and each value must match
    // its own grammar. None of these reaches live-grid even if a rule were wrong.
    "/grid/widgets.json?x=1", "/grid/live_grid?symbol=AAPL&admin=true",
    "/grid/live_grid?symbol=AAPL;DROP%20TABLE", "/grid/series?symbol=AAPL&provider=unapproved",
    "/grid/chart?symbol=AAPL&interval=7m", "/grid/chart?symbol=AAPL&theme=neon",
    "/grid/series?symbol=AAPL&start=yesterday",
    // The wire's own shape rules, each refused before any dial: nothing under /news/ but the
    // one history route; an unapproved feed id (0 can never be approved -- an id is >= 1 --
    // so this probe holds on every deployment); and a limit outside 1-50, refused whether or
    // not feed_id=1 happens to be one of the operator's approved ids.
    "/news/admin", "/news/api/news?feed_id=0&limit=1", "/news/api/news?feed_id=1&limit=51",
    // /ai (Rita): with "rita" off every path under it is unmatched. With it on, her document
    // answers (it dials her, never a vendor, so it is not probed); her POST is the only other
    // route, so its GET, a query, her other routes and anything else under /ai stay refused.
    ...(config.ritaUpstream ? [] : ["/ai/agents.json"]),
    "/ai/v1/query", "/ai/agents.json?x=1", "/ai/other", "/ai/v1/generate/code", "/ai/status",
    // The /api side forwards the whole catalogue, so the refusals to prove are
    // the SHAPE rules, not a provider allowlist: openbq-api's own interactive
    // surfaces, an uppercase route segment, and a control character in a value.
    // None of these reaches a provider even if the rule were wrong.
    "/api/docs", "/api/openapi.json", "/api/redoc", "/api/widgets.json?x=1",
    "/api/api/v1/Equity/price/quote",
    "/api/api/v1/equity/price/quote?symbol=AAPL%0d%0aX-Injected:%201",
    "/api/api/v1/calendar/trading?exchange=XNYS&year=2041", // outside the client's window
    "/api/api/v1/calendar/trading?exchange=XNYS"]) {         // missing year fails closed
    expect(await status(path, good), 404, `${path} with the token`);
  }
  // The same lock, then the same Origin rule, then the route: 101 once feeds are approved
  // (Serve mishandling a handshake shows up here and nowhere else), 503 while they are not.
  expect(await wsStatus({ Origin: config.origin }), 401, "an upgrade without a token");
  expect(await wsStatus({ ...good, Origin: "https://untrusted.invalid" }), 403, "an upgrade from a foreign Origin");
  const feeds = Object.keys(config.feeds).length;
  expect(await wsStatus({ ...good, Origin: config.origin }), feeds ? 101 : 503,
    feeds ? "an upgrade to the wire" : "an upgrade to the wire with no approved feeds");
  // The grid's socket, through the same two gates. On openbq-docker live-grid is the opt-in
  // `live` profile, so like the wire it has a "configured" state: 101 once settings.json says
  // it runs ("liveGrid": true), 503 while it does not. Opened and closed with no params frame,
  // so no symbol is ever subscribed.
  const grid = "/grid/live_grid_ws";
  expect(await wsStatus({ Origin: config.origin }, grid), 401, "a grid upgrade without a token");
  expect(await wsStatus({ ...good, Origin: "https://untrusted.invalid" }, grid), 403,
    "a grid upgrade from a foreign Origin");
  expect(await wsStatus({ ...good, Origin: config.origin }, grid), config.gridOrigin ? 101 : 503,
    config.gridOrigin ? "an upgrade to the grid" : "an upgrade to the grid with live-grid off");
  // A query on the QUOTE grid's socket route is refused: its whole subscription is the
  // first frame, so a ticket signed over a query string is not a ticket over anything this
  // door will open.
  expect(await wsStatus({ ...good, Origin: config.origin }, grid + "?symbol=AAPL"), 404,
    "a grid upgrade carrying a query");
  // The tick chart's socket is the opposite case, and the only one: live-grid's
  // /ta_chart_ws takes its whole parameter set from the query and reads no frame, so a BARE
  // upgrade is a refusal and a validated query would be a 101.
  //
  // REFUSALS ONLY here, on purpose -- see this function's own guarantee. That socket dials
  // live-grid at upgrade and live-grid immediately runs build_series, so a 101 probe would
  // make a real, possibly PAID upstream call from a gate that promises to make none. The lock
  // and the Origin rule are proved on the route as usual; then three shapes the route rules
  // refuse before anything is dialled -- no parameters, an unknown key, and a value outside
  // its grammar. That the admitted case really answers 101 is asserted in gateway.test.mjs,
  // against a fixture upstream.
  const taWs = "/grid/ta_chart_ws";
  expect(await wsStatus({ Origin: config.origin }, taWs + "?symbol=AAPL"), 401,
    "a tick-chart upgrade without a token");
  expect(await wsStatus({ ...good, Origin: "https://untrusted.invalid" }, taWs + "?symbol=AAPL"), 403,
    "a tick-chart upgrade from a foreign Origin");
  expect(await wsStatus({ ...good, Origin: config.origin }, taWs), 404,
    "a tick-chart upgrade with no parameters");
  expect(await wsStatus({ ...good, Origin: config.origin }, taWs + "?symbol=AAPL&provider=eodhd"), 404,
    "a tick-chart upgrade naming a provider");
  expect(await wsStatus({ ...good, Origin: config.origin }, taWs + "?symbol=AAPL&interval=7m"), 404,
    "a tick-chart upgrade outside the interval grammar");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await verify(readConfig(), process.env.GATEWAY_URL || "http://127.0.0.1:8091");
    console.log("PASS: machine auth, Host/Origin, blocked routes and all three socket routes "
      + "(the tick chart's by refusal only -- it dials at upgrade). No upstream data queried.");
  } catch (error) { console.error(`STOP: ${error.message}; no route should be opened.`); process.exitCode = 1; }
}
