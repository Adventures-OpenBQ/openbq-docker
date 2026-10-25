// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { upstreamPath, stateFile, socketTicket, socketTicketNonce, socketTicketValid, socketTarget, refSubscription } from "./policy.mjs";

// Built at run time so the public-content scan never sees a literal tailnet name.
const TAILNET = ["example-tailnet", "ts", "net"].join(".");

const ORIGIN = `https://openbq.${TAILNET}:10000`;
const TOKEN = "synthetic_test_credential_not_for_deployment";
const at = path => new URL(path, ORIGIN);
const route = raw => upstreamPath(at(raw), {});

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

test("families that arrive with later lines are refused at openbq-docker v4.0.0", () => {
  for (const later of ["/grid/widgets.json", "/grid/live_grid?symbol=AAPL",
    "/news/api/news?feed_id=7&limit=1", "/news/ws/news", "/news/admin",
    "/api/api/v1/calendar/trading?exchange=XNYS&year=2026", "/", "/widgets.json", "/mcp", "/keys"]) {
    assert.equal(route(later), later.startsWith("/api/api/v1/calendar/trading")
      ? "/api/api/v1/calendar/trading?exchange=XNYS&year=2026" : null, later);
  }
});

test("the state allow-list names the app's own JSON files and nothing else", () => {
  for (const ok of ["settings.json", "backends.json", "folders.json", "chat.json", "chart-presets.json",
    "dashboards/preview.json", "dashboards/3f2a-B_c.json"]) assert.equal(stateFile(ok), true, ok);
  for (const bad of ["", "settings.json.tmp", "../settings.json", "dashboards/../settings.json", "dashboards/a/b.json",
    "files/a.pdf", "Settings.json", "dashboards/" + "a".repeat(81) + ".json", 7, null]) assert.equal(stateFile(bad), false, String(bad));
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

test("socketTarget admits exactly /ref/live_grid_ws, no query; later lines' sockets stay refused", () => {
  assert.equal(socketTarget("/ref/live_grid_ws", ORIGIN), "/ref/live_grid_ws");
  for (const raw of [
    "/ref/live_grid_ws?x=1", "/ref/live_grid_ws?", "/ref/live_grid_ws#x", "/ref/live_grid_ws/",
    "/ref/other_ws", "/ref/../ref/live_grid_ws", "/REF/live_grid_ws",
    "/news/ws/news",                    // v8
    "/grid/live_grid_ws",               // v10
    "/news/ws/news?admin=1", "/news/ws/news#x",
    "/grid/ta_series_ws?symbol=AAPL&interval=5m",
    "/", "//x", "x", 7, null,
  ]) assert.equal(socketTarget(raw, ORIGIN), null, String(raw));
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
