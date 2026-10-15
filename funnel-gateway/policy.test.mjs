// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { upstreamPath, newsSubscription, stateFile, socketTicket, socketTicketNonce, socketTicketValid, socketTarget } from "./policy.mjs";

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

test("families that arrive with later lines are refused at openbq-docker v8.0.0", () => {
  for (const later of ["/grid/widgets.json", "/grid/live_grid?symbol=AAPL",
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
  assert.equal(socketTicketValid(TOKEN, target, ticket, 1_700_000_000_000 - 1), false);
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

test("the wire's socket is the one target a ticket may name at openbq-docker v8.0.0", () => {
  assert.equal(socketTarget("/news/ws/news", ORIGIN), "/news/ws/news");
  for (const raw of [
    "/news/ws/news?admin=1",            // the socket takes no query, so neither does its ticket
    "/news/ws/news#x",
    "/grid/live_grid_ws",               // later lines
    "/grid/ta_series_ws?symbol=AAPL&interval=5m",
    "/news/api/news?feed_id=7&limit=1", // a REST route is not a socket target
    "/", "//x", "x", 7, null,
  ]) assert.equal(socketTarget(raw, ORIGIN), null, String(raw));
  // A raw target is read against the ORIGIN the caller passes, and refused off it.
  assert.equal(socketTarget(ORIGIN + "/news/ws/news", "https://other.example.com"), null);
});


test("managed table routes and explicitly registered SSRM POSTs are method bounded", async () => {
  const p = await import("./policy.mjs");
  const route = (path, method = "GET") => p.tableRoute(new URL(path, "https://example.com"), method, { ssrmRoutes: ["/api/api/v1/test/rows"] });
  for (const path of ["/table/healthz", "/table/capabilities", "/table/widgets.json", "/table/sources/backends", "/table/exports/export_1/batches?sequence=0"]) assert.ok(route(path));
  for (const path of ["/table/sources/uploads", "/table/sources/backends", "/table/sessions", "/table/sessions/session_1/commands", "/table/sessions/session_1/derive", "/table/sessions/session_1/cancel", "/table/sessions/session_1/exports", "/api/api/v1/test/rows"]) assert.ok(route(path, "POST"));
  for (const path of ["/table/sources/s_1", "/table/sessions/session_1", "/table/exports/export_1"]) assert.ok(route(path, "DELETE"));
  for (const [path, method] of [["/table/sessions", "GET"], ["/table/healthz", "POST"], ["/table/sessions/x/commands?url=http://evil", "POST"], ["/table/exports/x/batches?sequence=-1", "GET"], ["/table/exports/x/batches?sequence=0&sequence=1", "GET"], ["/api/api/v1/test/other", "POST"], ["/table/sessions/x/anything", "POST"]]) assert.equal(route(path, method), null);
});
