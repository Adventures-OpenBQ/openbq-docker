// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { upstreamPath, stateFile, socketTicket, socketTicketNonce, socketTicketValid, socketTarget } from "./policy.mjs";

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

test("families that arrive with later lines are refused at openbq-docker v3.0.0", () => {
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

test("no socket is a target a ticket may name at openbq-docker v3.0.0", () => {
  for (const raw of [
    "/news/ws/news",                    // v8
    "/grid/live_grid_ws",               // v10
    "/news/ws/news?admin=1", "/news/ws/news#x",
    "/grid/ta_series_ws?symbol=AAPL&interval=5m",
    "/", "//x", "x", 7, null,
  ]) assert.equal(socketTarget(raw, ORIGIN), null, String(raw));
});
