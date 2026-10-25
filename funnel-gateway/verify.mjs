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
 * through the door proves Serve preserved it. The last three probes are WebSocket
 * upgrades on this tag's one socket route: the lock, the Origin rule, and then the route
 * itself -- 101 when the operator has approved feeds, 503 when they have not. A 101 here
 * opens the socket and closes it again without sending a subscription frame, so no upstream
 * connection to the wire is ever made and no article is fetched.
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
  function wsStatus(headers) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(new URL("/news/ws/news", socketBase), {
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
    "/tick", "/mcp", "/keys", "/widgets.json"]) {
    expect(await status(path), 401, `${path} without a token`);
  }
  expect(await status("/_gateway/health", { Authorization: "Bearer invalid" }), 401, "a wrong token");
  expect(await status("/_gateway/health", good), 200, "health through the lock");
  expect(await status("/_gateway/health", { ...good, Host: "untrusted.invalid" }), 421, "a foreign Host");
  expect(await status("/_gateway/health", { ...good, Origin: "https://untrusted.invalid" }), 403, "a foreign Origin");
  for (const path of ["/", "/tick", "/mcp", "/keys", "/widgets.json",
    // Families of later lines: refused at this tag.
    "/grid/live_grid?symbol=AAPL",
    // The wire's own shape rules, each refused before any dial: nothing under /news/ but the
    // one history route; an unapproved feed id (0 can never be approved -- an id is >= 1 --
    // so this probe holds on every deployment); and a limit outside 1-50, refused whether or
    // not feed_id=1 happens to be one of the operator's approved ids.
    "/news/admin", "/news/api/news?feed_id=0&limit=1", "/news/api/news?feed_id=1&limit=51",
    // openbq-docker serves no /ai (Rita): every path under it is unmatched.
    "/ai/agents.json", "/ai/v1/query", "/ai/agents.json?x=1", "/ai/other",
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
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await verify(readConfig(), process.env.GATEWAY_URL || "http://127.0.0.1:8091");
    console.log("PASS: machine auth, Host/Origin and blocked routes. No upstream data queried.");
  } catch (error) { console.error(`STOP: ${error.message}; no route should be opened.`); process.exitCode = 1; }
}
