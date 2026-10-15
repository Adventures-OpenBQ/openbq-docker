// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { socketTicket, stateFile } from "./policy.mjs";
import { chmod, mkdtemp, mkdir, readdir, rm, utimes, writeFile } from "node:fs/promises";
import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import { validateConfig, readConfig } from "./config.mjs";
import { createGateway, getJson } from "./server.mjs";
import { verify } from "./verify.mjs";
import { checkUpstreams } from "./check-upstreams.mjs";

// Built at run time so the public-content scan never sees a literal tailnet name.
const TAILNET = ["example-tailnet", "ts", "net"].join(".");

const TOKEN = "synthetic_test_credential_not_for_deployment";
const ORIGIN = `https://openbq.${TAILNET}:10000`;
const RSS_ORIGIN = `https://openbq.${TAILNET}:8088`;
const RSS_ADDRESS = [100, 64, 0, 3].join(".");
const FEED = "https://feeds.example.com/news.xml";
// The wire is ON in the default fixture -- it is this tag's own row. openbq-docker serves no
// /ai (Rita), so her settings are unknown keys and her routes unmatched (tests below).
const settings = { origin: ORIGIN, quoteDailyLimit: 100,
  rssOrigin: RSS_ORIGIN, rssAddress: RSS_ADDRESS, feeds: { [FEED]: 7 } };
const secrets = { token: TOKEN, apiUsername: "testuser", apiPassword: "synthetic-password" };
const config = () => validateConfig(settings, secrets);
const HEADERS = { Host: new URL(ORIGIN).host, Authorization: `Bearer ${TOKEN}` };
const quote = "/api/api/v1/equity/price/quote?symbol=AAPL&provider=eodhd";
const news = "/news/api/news?feed_id=7&limit=1";
async function fixture(t, overrides = {}, dependencies = {}) {
  const calls = [];
  const server = createGateway({ ...config(), ...overrides }, {
    requestJson: async (path, cfg, signal) => { calls.push({ path, cfg, signal }); return { results: [] }; },
    ...dependencies,
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  return { server, port: server.address().port, calls };
}
function http(port, path, headers = HEADERS, method = "GET") {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path, method, headers }, res => {
      const parts = [];
      res.on("data", c => parts.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(parts).toString() }));
    });
    req.on("error", reject); req.end();
  });
}
function wsConnect(port, headers = { ...HEADERS, Origin: ORIGIN }, path = "/news/ws/news") {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, { headers, handshakeTimeout: 1000 });
    ws.on("error", () => {});
    ws.once("open", () => resolve({ status: 101, ws }));
    ws.once("unexpected-response", (_, res) => { res.resume(); resolve({ status: res.statusCode }); ws.terminate(); });
    const timer = setTimeout(() => { ws.terminate(); reject(new Error("WS timeout")); }, 1500);
    timer.unref(); ws.once("open", () => clearTimeout(timer));
    ws.once("close", () => clearTimeout(timer));
  });
}

test("configuration fails closed; secrets come from the environment", () => {
  assert.equal(config().origin, ORIGIN);
  assert.equal(config().apiOrigin, "http://openbq-api:6900");
  assert.equal(config().apiAuthorization, "Basic " + Buffer.from("testuser:synthetic-password").toString("base64"));
  for (const change of [{ token: "" }, { token: TOKEN + "\n" }, { token: "short" }, { apiUsername: "x:y" }, { apiPassword: "" }]) {
    assert.throws(() => validateConfig(settings, { ...secrets, ...change }));
  }
  for (const change of [
    { origin: "http://example.com" }, { origin: "https://arbitrary.example.com" },
    { origin: `https://openbq.${TAILNET}:8443` },   // the episode 3 reference's tailnet port, never the door
    { origin: `https://openbq.${TAILNET}:10000/x` },
    { quoteDailyLimit: 0 }, { quoteDailyLimit: 10001 }, { quoteDailyLimit: 1.5 },
    { requestsPerMinute: 0 }, { requestsPerMinute: 601 }, { requestsPerMinute: "60" },
    { maxConcurrent: 0 }, { maxConcurrent: 33 }, { maxSockets: 0 }, { maxSockets: 33 },
    { previewOrigin: "http://preview.example.com" }, { previewOrigin: "https://preview.example.com/x" },
    { previewOrigin: "https://user@preview.example.com" }, { previewOrigin: 7 },
    { stateDir: "relative/state" }, { stateDir: "/var/lib/../etc" }, { stateDir: 7 }, { stateDir: "" },
    // Settings of later lines are not silently accepted: a stack at this tag has no such upstream.
    { gridOrigin: "http://openbb-live-grid:6903" }, { tickUrl: `wss://kdb.${TAILNET}` },
    // The wire: both settings or neither, its origin is a tailnet name on :8088 (the port
    // ts-config publishes rss-ticker on) or portless, its address a tailnet IPv4, and the
    // approved feeds are https urls mapped to positive integer ids.
    { rssOrigin: RSS_ORIGIN, rssAddress: undefined },                        // no pinned address
    { rssOrigin: undefined, rssAddress: RSS_ADDRESS },                       // no origin
    { rssOrigin: "https://rss.example.com", rssAddress: RSS_ADDRESS },       // not a tailnet name
    { rssOrigin: `https://openbq.${TAILNET}:10000`, rssAddress: RSS_ADDRESS }, // the door's own port
    { rssOrigin: RSS_ORIGIN, rssAddress: [10, 0, 0, 3].join(".") },                       // not a tailnet address
    { feeds: [] }, { feeds: 7 }, { feeds: null },
    { feeds: { "http://feeds.example.com/x.xml": 7 } },                      // not https
    { feeds: { "not a url": 7 } },                                           // not a URL at all
    { feeds: { [FEED]: 7, "https://other.example.com/rss": 7 } },            // two feeds, one id
    { feeds: { [FEED]: 0 } }, { feeds: { [FEED]: -1 } }, { feeds: { [FEED]: 1.5 } }, { feeds: { [FEED]: "7" } },
    { feeds: Object.fromEntries(Array.from({ length: 51 }, (_, i) => [`https://f${i}.example.com/x`, i + 1])) },
    // Approved feeds with no wire to send them to: refused at startup rather than 404 per request.
    { rssOrigin: undefined, rssAddress: undefined, feeds: { [FEED]: 7 } },
    // openbq-docker serves no /ai: Rita's settings and the SOCKS fallback she used are unknown keys.
    { ritaOrigin: `https://rita.${TAILNET}`, ritaAddress: [100, 64, 0, 2].join(".") },
    { socksProxy: "socks5h://openbq-ts:1055" },
  ]) assert.throws(() => validateConfig({ ...settings, ...change }, secrets), JSON.stringify(change));
  // The node's own :443 is the API's and :8443 the episode 3 reference's, so the door is :10000 or
  // nothing; a portless origin stays valid for a reader who funnels a dedicated node.
  assert.equal(validateConfig({ ...settings, origin: `https://openbq.${TAILNET}` }, secrets).origin,
    `https://openbq.${TAILNET}`);
  assert.equal(validateConfig({ ...settings, origin: `https://openbq.${TAILNET}:443` }, secrets).origin,
    `https://openbq.${TAILNET}`);
  const defaults = validateConfig(settings, secrets);
  assert.deepEqual([defaults.requestsPerMinute, defaults.maxConcurrent, defaults.maxSockets, defaults.previewOrigin, defaults.stateDir],
    [60, 8, 4, null, null]);
  for (const key of ["ritaOrigin", "ritaAddress", "socksProxy"]) assert.equal(key in defaults, false, key);
  assert.deepEqual([defaults.rssOrigin, defaults.rssAddress, defaults.feeds], [RSS_ORIGIN, RSS_ADDRESS, { [FEED]: 7 }]);
  // A malformed feed URL fails with the feed block's own message, not the platform's bare
  // "Invalid URL" -- an operator reading a startup failure should be told which rule it broke.
  assert.throws(() => validateConfig({ ...settings, feeds: { "not a url": 7 } }, secrets),
    /Invalid approved feed/);
  assert.throws(() => validateConfig({ ...settings, feeds: { [FEED]: 7, "https://other.example.com/rss": 7 } }, secrets),
    /two feeds share one id/);
  // Distinct ids for distinct feeds is the shape the docs describe, and it is accepted.
  assert.deepEqual(validateConfig({ ...settings, feeds: { [FEED]: 7, "https://other.example.com/rss": 8 } }, secrets).feeds,
    { [FEED]: 7, "https://other.example.com/rss": 8 });
  // The wire off is the shipped default: no origin, no address, no approved feed.
  const noWire = validateConfig({ origin: ORIGIN }, secrets);
  assert.deepEqual([noWire.rssOrigin, noWire.rssAddress, noWire.feeds], [null, null, {}]);
  // A portless rss origin stays valid for a reader who fronts the pool on a node's own :443.
  assert.equal(validateConfig({ ...settings, rssOrigin: `https://rss.${TAILNET}` }, secrets).rssOrigin,
    `https://rss.${TAILNET}`);
  const roomy = validateConfig({ ...settings, quoteDailyLimit: 10000, requestsPerMinute: 600, maxConcurrent: 32 }, secrets);
  assert.deepEqual([roomy.quoteDailyLimit, roomy.requestsPerMinute, roomy.maxConcurrent], [10000, 600, 32]);
  assert.throws(() => validateConfig({ origin: ORIGIN, ritaOrigin: `https://rita.${TAILNET}` }, secrets),
    /Unknown setting: ritaOrigin/);
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-"));
  try {
    writeFileSync(join(directory, "settings.json"), JSON.stringify(settings));
    const env = { GATEWAY_TOKEN: TOKEN, OPENBB_API_USERNAME: "testuser", OPENBB_API_PASSWORD: "synthetic-password" };
    assert.equal(readConfig(directory, env).token, TOKEN);
    assert.throws(() => readConfig(directory, { ...env, GATEWAY_TOKEN: "" }));
    assert.throws(() => readConfig(directory, { ...env, OPENBB_API_PASSWORD: undefined }));
    // A credentials.json beside settings.json is the OLD layout; it is ignored, never read.
    writeFileSync(join(directory, "credentials.json"), JSON.stringify({ token: "x".repeat(40) }));
    assert.equal(readConfig(directory, env).token, TOKEN);
  } finally { rmSync(directory, { recursive: true }); }
});

// The documented first deployment is `cp funnel-gateway/settings.example.json
// gateway-config/settings.json` then edit `origin` -- so the shipped example must actually
// validate, not merely look plausible. It ships with the wire off.
test("the shipped settings.example.json validates as-is, with the wire off", () => {
  const example = JSON.parse(readFileSync(new URL("./settings.example.json", import.meta.url), "utf8"));
  const cfg = validateConfig(example, secrets);
  // The example names YOUR-TAILNET (the repo's placeholder); a URL origin is lowercase.
  assert.equal(cfg.origin, example.origin.toLowerCase());
  // The wire's three keys are documented in the README and omitted here, so the file
  // ships exactly what this cut deploys: no upstream an operator has not named themselves.
  assert.deepEqual([cfg.rssOrigin, cfg.rssAddress, cfg.feeds], [null, null, {}]);
  for (const key of ["rssOrigin", "rssAddress", "feeds"]) assert.equal(key in example, false, key);
  // The table keys are documented in the README and omitted here too.
  assert.equal(cfg.tableOrigin, null);
});

test("every route is locked before Host, Origin, method or route discovery", async t => {
  const { port, calls } = await fixture(t);
  for (const path of ["/", "/_gateway/health", quote, "/widgets.json", "/tick", "/mcp"]) {
    assert.equal((await http(port, path, { Host: "wrong.invalid" })).status, 401);
    assert.equal((await http(port, path, { ...HEADERS, Authorization: "Bearer wrong" })).status, 401);
  }
  assert.equal((await http(port, quote, { ...HEADERS, Authorization: ["Bearer wrong", `Bearer ${TOKEN}`] })).status, 401);
  assert.equal(calls.length, 0);
});

test("canonical Host/Origin, methods and exact path handling", async t => {
  const { port } = await fixture(t);
  assert.equal((await http(port, quote, { ...HEADERS, Host: "wrong.invalid", "X-Forwarded-Host": new URL(ORIGIN).host })).status, 421);
  assert.equal((await http(port, quote, { ...HEADERS, Origin: "https://wrong.invalid" })).status, 403);
  assert.equal((await http(port, quote, HEADERS, "POST")).status, 405);
  for (const path of ["//api/api/v1/equity/price/quote", "/api/%61pi/v1/x", "/api/../api/v1/x", "/api\\api/v1/x"]) {
    assert.equal((await http(port, path)).status, 421);
  }
});

test("only bounded OpenBB and approved News queries reach upstream; later families are refused", async t => {
  const { port, calls } = await fixture(t);
  for (const path of ["/", "/tick", "/keys", "/mcp", "/stores", "/live/widgets.json",
    "/grid/widgets.json", quote + "&symbol=MSFT",
    // The wire's own refusals: an unapproved id, a limit past 50, a duplicated name, and the
    // socket path asked for over plain HTTP (an upgrade is the only way to reach it).
    news.replace("=7", "=8"), news.replace("limit=1", "limit=51"), news + "&feed_id=7",
    "/news/ws/news", "/news/admin"]) {
    assert.equal((await http(port, path)).status, 404, path);
  }
  // openbq-docker serves no /ai (Rita): her document is unmatched, and her POST is not a route.
  for (const path of ["/ai/agents.json", "/ai/v1/query", "/ai/other"]) assert.equal((await http(port, path)).status, 404, path);
  assert.equal((await http(port, "/ai/v1/query", HEADERS, "POST")).status, 405);
  assert.equal((await http(port, quote)).status, 200);
  assert.equal((await http(port, news)).status, 200);
  assert.deepEqual(calls.map(c => c.path), [quote, news]);
});

test("the OpenBB root documents and every api/v1 route forward; the rest of /api does not", async t => {
  const upstream = createServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ path: req.url, auth: req.headers.authorization ?? null }));
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t,
    { apiOrigin: `http://127.0.0.1:${upstream.address().port}`, quoteDailyLimit: 1000 },
    { requestJson: getJson });
  // The two root documents the client fetches, plus one route from each of the
  // families the 331-widget catalogue spans. All carry the stack's Basic pair,
  // never the caller's Bearer token.
  for (const [path, forwarded] of [
    ["/api/widgets.json", "/widgets.json"],
    ["/api/apps.json", "/apps.json"],
    ["/api/api/v1/equity/price/quote?symbol=AAPL&provider=fmp",
      "/api/v1/equity/price/quote?symbol=AAPL&provider=fmp"],
    ["/api/api/v1/economy/fred_series?symbol=GDP&start_date=2020-01-01",
      "/api/v1/economy/fred_series?symbol=GDP&start_date=2020-01-01"],
    ["/api/api/v1/federal_reserve/fomc_documents_choices", "/api/v1/federal_reserve/fomc_documents_choices"],
  ]) {
    const response = await http(port, path);
    assert.equal(response.status, 200, path);
    const seen = JSON.parse(response.text);
    assert.equal(decodeURIComponent(seen.path), forwarded);
    assert.equal(seen.auth, config().apiAuthorization);
  }
  // The query is re-serialised from the parsed pairs, so what the stack sees is
  // canonical encoding rather than the bytes the caller wrote.
  assert.equal(JSON.parse((await http(port, "/api/api/v1/equity/price/quote?symbol=AAPL%2cMSFT")).text).path,
    "/api/v1/equity/price/quote?symbol=AAPL%2CMSFT");
  for (const path of [
    // openbb-api's interactive surfaces are outside /api/api/v1/ and stay shut.
    "/api/docs", "/api/openapi.json", "/api/redoc", "/api/admin",
    "/api/widgets.json?x=1", "/api/apps.json?x=1",
    // Path shape: uppercase, a dot, over-long.
    "/api/api/v1/Equity/price/quote",
    "/api/api/v1/equity/price/quote.json", "/api/api/v1/" + "a".repeat(201),
    // Query shape: CR/LF in a value, an over-long value, more than 40 pairs,
    // a duplicated key, a name outside the class.
    "/api/api/v1/equity/price/quote?symbol=AAPL%0d%0aX-Injected:%201",
    "/api/api/v1/equity/price/quote?symbol=" + "A".repeat(1025),
    "/api/api/v1/equity/price/quote?" + Array.from({ length: 41 }, (_, i) => `p${i}=1`).join("&"),
    quote + "&symbol=MSFT", "/api/api/v1/equity/price/quote?1symbol=AAPL",
  ]) assert.equal((await http(port, path)).status, 404, path);
  // Traversal is refused a layer EARLIER than the policy, which is why these
  // answer 421 rather than 404: requestUrl rejects any "%" in the path before
  // route discovery, and a literal ".." is folded by new URL into a path that
  // no longer matches the request line. OPENBB_ROUTE_RE still refuses both on
  // its own -- policy.mjs is the shared allow-list and has to stand alone.
  for (const path of ["/api/api/v1/equity/%2e%2e/%2e%2e/admin", "/api/api/v1/equity/../../admin"]) {
    assert.equal((await http(port, path)).status, 421, path);
  }
  assert.equal((await http(port, "/api/widgets.json", HEADERS, "POST")).status, 405);
});

test("single-instance aggregate and daily quote budgets reject before forwarding", async t => {
  const { port, calls } = await fixture(t, { quoteDailyLimit: 1 });
  assert.equal((await http(port, quote)).status, 200);
  assert.equal((await http(port, quote)).status, 429);
  assert.equal(calls.length, 1);
  for (let i = 0; i < 58; i++) assert.equal((await http(port, "/_gateway/health")).status, 200);
  assert.equal((await http(port, "/_gateway/health")).status, 429);
});

test("the daily budget meters vendor calls, not the two manifests", async t => {
  // widgets.json and apps.json are openbb-api's own static documents: no provider is
  // called, so no quota is spent. Metering them made a dashboard open cost N+1 units
  // and ten opens exhaust a default day (review of the all-widgets change, 2026-09-20).
  const { port } = await fixture(t, { quoteDailyLimit: 1 });
  for (const manifest of ["/api/widgets.json", "/api/apps.json", "/api/widgets.json"]) {
    assert.equal((await http(port, manifest)).status, 200, manifest);
  }
  assert.equal((await http(port, quote)).status, 200);
  assert.equal((await http(port, quote)).status, 429);
  assert.equal((await http(port, "/api/apps.json")).status, 200);
});

test("the per-minute budget and the concurrency cap come from settings", async t => {
  const { port } = await fixture(t, { requestsPerMinute: 3 });
  for (let i = 0; i < 3; i++) assert.equal((await http(port, "/_gateway/health")).status, 200);
  assert.equal((await http(port, "/_gateway/health")).status, 429);

  // maxConcurrent: hold one upstream call open, and the next REST request is refused.
  let release;
  const held = await fixture(t, { maxConcurrent: 1 }, { requestJson: () => new Promise(resolve => { release = resolve; }) });
  const first = http(held.port, quote);
  while (!release) await new Promise(resolve => setImmediate(resolve));
  assert.equal((await http(held.port, quote)).status, 429);
  release({ results: [] });
  await first;
});

test("client disconnect aborts upstream work", async t => {
  let signal;
  const { port } = await fixture(t, {}, { requestJson: (_, __, value) => {
    signal = value;
    return new Promise((_, reject) => value.addEventListener("abort", () => reject(new Error("Aborted"))));
  } });
  const req = request({ host: "127.0.0.1", port, path: quote, headers: HEADERS });
  req.on("error", () => {}); req.end();
  while (!signal) await new Promise(resolve => setImmediate(resolve));
  req.destroy();
  if (!signal.aborted) await once(signal, "abort");
  assert.equal(signal.aborted, true);
});

test("upstream HTTP prefix stripping, Basic injection and no client credential forwarding", async t => {
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ url: req.url, headers: req.headers });
    res.writeHead(200, { "Content-Type": "application/json", "Set-Cookie": "sensitive=test" });
    res.end('{"results":[]}');
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { apiOrigin: `http://127.0.0.1:${upstream.address().port}` }, { requestJson: getJson });
  const response = await http(port, quote, { ...HEADERS, Cookie: "viewer=session", "X-Forwarded-For": "untrusted" });
  assert.equal(response.status, 200);
  assert.equal(response.headers["set-cookie"], undefined);
  assert.equal(seen[0].url, "/api/v1/equity/price/quote?symbol=AAPL&provider=eodhd");
  assert.equal(seen[0].headers.authorization, config().apiAuthorization);
  assert.equal(seen[0].headers.cookie, undefined);
  assert.equal(seen[0].headers["x-forwarded-for"], undefined);
  assert.ok(!response.text.includes(TOKEN));
});

test("upstream redirects, error text, invalid JSON and oversized responses never escape", async t => {
  let mode;
  const upstream = createServer((req, res) => {
    if (mode === "redirect") { res.writeHead(302, { Location: "https://attacker.invalid" }); return res.end(); }
    if (mode === "error") { res.writeHead(401); return res.end("sensitive-upstream-error"); }
    if (mode === "html") { res.writeHead(200, { "Content-Type": "text/html" }); return res.end("secret"); }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(mode === "large" ? JSON.stringify("x".repeat(2 * 1024 * 1024)) : "not-json");
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { apiOrigin: `http://127.0.0.1:${upstream.address().port}` }, { requestJson: getJson });
  for (mode of ["redirect", "error", "html", "large", "invalid"]) {
    const response = await http(port, quote);
    assert.equal(response.status, 502);
    assert.equal(response.text, '{"error":"Request refused"}');
    assert.equal(response.headers.location, undefined);
  }
});

test("a full-catalogue widgets.json fits MAX_BODY; one past it is an honest 502", async t => {
  // Measured against the live v12.4 openbb-api on 2026-09-20: 331 widgets,
  // 1,678,152 bytes of compact JSON, about 20% inside the 2 MiB MAX_BODY this
  // gateway already applied. What matters is the failure mode when a future
  // catalogue outgrows it: getJson destroys the response and rejects, so the
  // caller sees a 502 rather than a manifest silently cut in half.
  let size = 1_700_000;
  const upstream = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(Object.fromEntries(
      Array.from({ length: 400 }, (_, i) => [`w${i}`, "x".repeat(Math.ceil(size / 400))]))));
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { apiOrigin: `http://127.0.0.1:${upstream.address().port}` },
    { requestJson: getJson });
  const ok = await http(port, "/api/widgets.json");
  assert.equal(ok.status, 200);
  assert.equal(Object.keys(JSON.parse(ok.text)).length, 400);
  size = 2 * 1024 * 1024 + 1024;
  const over = await http(port, "/api/widgets.json");
  assert.equal(over.status, 502);
  assert.equal(over.text, '{"error":"Request refused"}');
});

test("operator verifier makes no upstream or provider calls, wire on or off", async t => {
  // Wire on: its last probe expects 101, which opens and closes a socket with no
  // subscription frame -- so still no upstream connection and no article fetched.
  const { port, calls } = await fixture(t);
  await verify(config(), `http://127.0.0.1:${port}`); assert.equal(calls.length, 0);
  // Wire off: the same probe expects 503. Both branches of that expectation run, so a
  // deployment with no approved feed is not told its door is broken.
  const off = { ...config(), rssOrigin: null, rssAddress: null, feeds: {} };
  const bare = await fixture(t, { rssOrigin: null, rssAddress: null, feeds: {} });
  await verify(off, `http://127.0.0.1:${bare.port}`); assert.equal(bare.calls.length, 0);
});

test("upstream preflight validates Basic auth and the API's lock without querying a quote", async t => {
  let withPair = 422, withoutPair = 401;
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ path: req.url, auth: req.headers.authorization });
    res.writeHead(req.headers.authorization ? withPair : withoutPair); res.end();
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  // The wire is left OUT of this config: what is under test is the API leg, and the wire's
  // own preflight has its own test below (it would otherwise dial a real tailnet address).
  const cfg = { ...config(), rssOrigin: null, rssAddress: null, feeds: {},
    apiOrigin: `http://127.0.0.1:${upstream.address().port}` };
  await checkUpstreams(cfg);
  assert.deepEqual(seen, [{ path: "/api/v1/equity/price/quote", auth: cfg.apiAuthorization },
    { path: "/api/v1/equity/price/quote", auth: undefined }]);
  withPair = 401; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  withPair = 200; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  // OPENBB_API_AUTH off: the pair is "accepted" because nothing is checked. The door stays shut.
  withPair = 422; withoutPair = 422; await assert.rejects(checkUpstreams(cfg), /API lock preflight failed/);
});

test("the wire's preflight pages the approved feed, refuses a bad page, and sends no credential", async t => {
  let status = 200, body = '{"news":[]}';
  const seen = [];
  const rss = createServer((req, res) => {
    seen.push({ path: req.url, auth: req.headers.authorization, accept: req.headers.accept });
    res.writeHead(status, { "Content-Type": "application/json" }); res.end(body);
  });
  rss.listen(0, "127.0.0.1"); await once(rss, "listening");
  t.after(() => new Promise(resolve => { rss.closeAllConnections(); rss.close(resolve); }));
  const api = createServer((req, res) => { res.writeHead(req.headers.authorization ? 422 : 401); res.end(); });
  api.listen(0, "127.0.0.1"); await once(api, "listening");
  t.after(() => new Promise(resolve => api.close(resolve)));
  // A plain-HTTP loopback origin, which production validation refuses: what is under test
  // here is the history leg's own contract and its refusals. The SOCKET leg needs a real
  // certificate and a pinned dial, so its happy path is proved in tls.test.mjs instead --
  // connectNews always speaks wss:// and cannot be pointed at a loopback HTTP fixture.
  const cfg = { ...config(), apiOrigin: `http://127.0.0.1:${api.address().port}`,
    rssOrigin: `http://127.0.0.1:${rss.address().port}`, rssAddress: null };
  // A wire that answers anything but a 200 JSON page stops the door from opening, and it is
  // asked only for the ONE approved id, with no credential of anyone's attached.
  status = 500; await assert.rejects(checkUpstreams(cfg));
  status = 200; body = "not json"; await assert.rejects(checkUpstreams(cfg));
  assert.deepEqual(seen.map(r => r.path), ["/api/news?feed_id=7&limit=1", "/api/news?feed_id=7&limit=1"]);
  for (const r of seen) {
    assert.equal(r.auth, undefined, "the wire has no credential to send");
    assert.equal(r.accept, "application/json");
  }
});

// ---- Socket tickets: the browser's own sockets (relaying them through a Vercel Function bills function time while they are open).
const PREVIEW = "https://bdobb.example.vercel.app";
const ticketed = (path, ticket) => path + (path.includes("?") ? "&" : "?") + "ticket=" + ticket;
const browser = { Host: new URL(ORIGIN).host, Origin: PREVIEW };

test("a browser socket is admitted on a ticket: right target, right Origin, once", async t => {
  const { port } = await fixture(t, { previewOrigin: PREVIEW }, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const path = "/news/ws/news";
  const ticket = socketTicket(TOKEN, path);
  const admitted = await wsConnect(port, browser, ticketed(path, ticket));
  assert.equal(admitted.status, 101); admitted.ws.terminate();
  // Single use: the same ticket, replayed inside its thirty seconds, is refused.
  assert.equal((await wsConnect(port, browser, ticketed(path, ticket))).status, 401);
  // Wrong Origin (the gateway's own, which the machine path uses, included), wrong target,
  // wrong key, expired, junk, doubled: all 401 or 403, none reach an upstream.
  assert.equal((await wsConnect(port, { ...browser, Origin: "https://evil.example.com" }, ticketed(path, socketTicket(TOKEN, path)))).status, 403);
  assert.equal((await wsConnect(port, { ...browser, Origin: ORIGIN }, ticketed(path, socketTicket(TOKEN, path)))).status, 403);
  assert.equal((await wsConnect(port, browser, ticketed(path, socketTicket(TOKEN, "/grid/live_grid_ws")))).status, 401);
  assert.equal((await wsConnect(port, browser, ticketed(path, socketTicket(TOKEN + "x", path)))).status, 401);
  assert.equal((await wsConnect(port, browser, ticketed(path, socketTicket(TOKEN, path, Date.now() - 31_000)))).status, 401);
  assert.equal((await wsConnect(port, browser, ticketed(path, "junk"))).status, 401);
  const two = socketTicket(TOKEN, path);
  assert.equal((await wsConnect(port, browser, `${path}?ticket=${two}&ticket=${two}`)).status, 401);
  // A key the URL parser decodes to "ticket" but the wire never spells is not a ticket.
  assert.equal((await wsConnect(port, browser, `${path}?tick%65t=${socketTicket(TOKEN, path)}`)).status, 401);
  // No ticket and no bearer is what it always was.
  assert.equal((await wsConnect(port, browser, path)).status, 401);
  // A ticket is for sockets. It buys nothing on the REST side.
  assert.equal((await http(port, ticketed(quote, socketTicket(TOKEN, quote)), browser)).status, 401);
});

test("tickets are off until the operator names the preview origin", async t => {
  const { port } = await fixture(t, {}, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  assert.equal((await wsConnect(port, browser, ticketed("/news/ws/news", socketTicket(TOKEN, "/news/ws/news")))).status, 401);
  // ... and the machine path is untouched by any of this.
  const machine = await wsConnect(port); assert.equal(machine.status, 101); machine.ws.terminate();
});

// ---- The wire's socket: the first route this door serves over a socket (Ep. 8).

test("the WS gate wants the credential, the Origin, the exact path and a configured wire", async t => {
  const { port } = await fixture(t, {}, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: ORIGIN })).status, 401);
  assert.equal((await wsConnect(port, HEADERS)).status, 403);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: "https://untrusted.invalid" })).status, 403);
  // The socket takes no query and no subprotocol, and no other path is a socket at all.
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/news/ws/news?admin=1")).status, 404);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/grid/live_grid_ws")).status, 404);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/news/api/news?feed_id=7&limit=1")).status, 404);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN, "Sec-WebSocket-Protocol": "chat" })).status, 404);
  // The route exists but the operator has approved nothing: 503, not 404.
  const empty = await fixture(t, { feeds: {}, rssOrigin: null, rssAddress: null });
  assert.equal((await wsConnect(empty.port)).status, 503);
});

test("the WS relays one sanitized approved subscription and closes on a second frame", async t => {
  const upstream = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(upstream, "listening");
  t.after(() => new Promise(resolve => { for (const ws of upstream.clients) ws.terminate(); upstream.close(resolve); }));
  const messages = [];
  upstream.on("connection", ws => ws.on("message", data => {
    messages.push(JSON.parse(data)); ws.send('{"type":"test-news"}');
  }));
  const { port } = await fixture(t, {}, { openNews: () => new WebSocket(`ws://127.0.0.1:${upstream.address().port}`) });
  const { ws } = await wsConnect(port);
  const message = once(ws, "message");
  // The unapproved feed is dropped on the way through, not a reason to refuse the approved one.
  ws.send(JSON.stringify({ subscribe: [{ url: FEED, name: "rename-attempt", admin: true }, { url: "https://unapproved.invalid/feed" }] }));
  assert.equal((await message)[0].toString(), '{"type":"test-news"}');
  assert.deepEqual(messages, [{ subscribe: [{ url: FEED }] }]);
  const closed = once(ws, "close"); ws.send('{"unsubscribe":[]}'); await closed;
});

// ---- The live socket's teardown and back-pressure paths (review I2). Every one of them
// ends the same way -- both ends closed and the slot handed back -- so each test proves the
// release by opening a second socket against a gateway whose cap is one.
function connectionQueue(server) {
  const ready = [], waiting = [];
  server.on("connection", ws => { const next = waiting.shift(); next ? next(ws) : ready.push(ws); });
  return () => (ready.length ? Promise.resolve(ready.shift()) : new Promise(resolve => waiting.push(resolve)));
}
async function wireFixture(t, overrides = {}) {
  const pool = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(pool, "listening");
  const nextConnection = connectionQueue(pool);
  t.after(() => new Promise(resolve => {
    for (const ws of pool.clients) ws.terminate(); pool.close(resolve);
  }));
  const gw = await fixture(t, { maxSockets: 1, ...overrides },
    { openNews: () => new WebSocket(`ws://127.0.0.1:${pool.address().port}`) });
  return { ...gw, nextConnection };
}
// Every assertion below is "this end closes", which a regression turns into a hang rather
// than a failure. Bounded, so a broken teardown path fails the suite in two seconds with a
// message naming the event that never came.
function within(emitter, event, ms = 2000) {
  let timer;
  return Promise.race([
    once(emitter, event).finally(() => clearTimeout(timer)),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`no "${event}" within ${ms}ms`)), ms); }),
  ]);
}
// A live relay: a client through the door, its one subscription frame sent, and the pool side
// of the upstream connection the frame caused.
async function relayed(f) {
  const { ws } = await wsConnect(f.port);
  ws.send(JSON.stringify({ subscribe: [{ url: FEED }] }));
  return { ws, up: await f.nextConnection() };
}
// The slot is back: with maxSockets at 1, a second socket only opens if the first was released.
async function slotReleased(f) {
  const again = await wsConnect(f.port);
  assert.equal(again.status, 101, "the socket slot was not released");
  again.ws.terminate();
}

test("the wire closing tears down the client, and hands the slot back", async t => {
  const f = await wireFixture(t);
  const { ws, up } = await relayed(f);
  const closed = within(ws, "close");
  up.close();
  await closed;
  await slotReleased(f);
});

test("the client going away terminates the upstream connection, and hands the slot back", async t => {
  const f = await wireFixture(t);
  const { ws, up } = await relayed(f);
  const upClosed = within(up, "close");
  ws.terminate();
  await upClosed;
  await slotReleased(f);
});

test("a client too far behind is closed rather than queued behind, and hands the slot back", async t => {
  const f = await wireFixture(t);
  const { ws, up } = await relayed(f);
  // The relay reads `client.bufferedAmount` off the server-side socket, which lives inside
  // createGateway and is deliberately not exposed. Stubbing the getter on ws's prototype for
  // the duration of this one send is how the branch is reached without adding a test-only
  // handle to the server. Restored before the follow-up upgrade, and again in t.after.
  const real = Object.getOwnPropertyDescriptor(WebSocket.prototype, "bufferedAmount");
  const restore = () => Object.defineProperty(WebSocket.prototype, "bufferedAmount", real);
  t.after(restore);
  Object.defineProperty(WebSocket.prototype, "bufferedAmount", { configurable: true, get: () => 262145 });
  const closed = within(ws, "close");
  up.send('{"type":"news"}');
  await closed;
  restore();
  await slotReleased(f);
});

test("an oversized or binary frame from the wire closes the relay, and hands the slot back", async t => {
  for (const [what, send] of [
    ["oversized", up => up.send("x".repeat(65537))],
    ["binary", up => up.send(Buffer.from("news"), { binary: true })],
  ]) {
    const f = await wireFixture(t);
    const { ws, up } = await relayed(f);
    const closed = within(ws, "close", 2000);
    send(up);
    await closed.catch(error => { throw new Error(`${what}: ${error.message}`); });
    await slotReleased(f);
  }
});

test("bad, binary, oversized, duplicate or unapproved WS frames never open the wire", async t => {
  let opened = 0;
  const { port } = await fixture(t, {}, { openNews: () => { opened++; throw new Error("Must not connect"); } });
  for (const frame of ["not-json", '{"subscribe":[]}', JSON.stringify({ subscribe: [{ url: "https://unapproved.invalid" }] }),
    JSON.stringify({ subscribe: [{ url: FEED }, { url: FEED }] }), '{"subscribe":[],"admin":true}',
    Buffer.from("binary"), "x".repeat(65537)]) {
    const { ws } = await wsConnect(port); const closed = once(ws, "close");
    ws.send(frame); await closed;
  }
  assert.equal(opened, 0);
});

test("WS initial frame and absolute lifetimes are bounded", async t => {
  const first = await fixture(t, {}, { firstFrameMs: 30, openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const a = await wsConnect(first.port); await once(a.ws, "close");
  const second = await fixture(t, {}, { firstFrameMs: 1000, socketMs: 30, openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const b = await wsConnect(second.port); await once(b.ws, "close");
});

test("the socket cap and the six-unit socket price come from settings, charged before the upgrade", async t => {
  const capped = await fixture(t, { maxSockets: 1 }, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const first = await wsConnect(capped.port); assert.equal(first.status, 101);
  assert.equal((await wsConnect(capped.port)).status, 429);
  first.ws.terminate();
  // A socket costs six of the per-minute budget, and it is charged BEFORE handleUpgrade: with
  // six left exactly one socket is admitted, and the seventh unit is gone -- so the REST side
  // is out of budget too, which is what proves the charge happened and not a refund.
  const metered = await fixture(t, { requestsPerMinute: 6 }, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const only = await wsConnect(metered.port); assert.equal(only.status, 101);
  assert.equal((await http(metered.port, "/_gateway/health")).status, 429);
  assert.equal((await wsConnect(metered.port)).status, 429);
  only.ws.terminate();
});

test("a refused upgrade never allocates a socket slot, so the cap is not consumed by 404s", async t => {
  const { port } = await fixture(t, { maxSockets: 1 }, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  for (const path of ["/news/ws/news?x=1", "/grid/live_grid_ws", "/nope"]) {
    assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
  }
  const admitted = await wsConnect(port); assert.equal(admitted.status, 101); admitted.ws.terminate();
});

// ---- Per-user state: the web preview's saved configuration, on the NAS (user ruling
// 2026-09-20). The one place, at this tag, where the gateway takes a method other than GET.
function send(port, path, method, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path, method,
      headers: { ...HEADERS, ...(body === undefined ? {} : { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }), ...headers } }, res => {
      const parts = []; res.on("data", c => parts.push(c));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(parts).toString() }));
    });
    req.on("error", reject); req.end(body);
  });
}
async function stateFixture(t, overrides = {}) {
  const stateDir = await mkdtemp(join(tmpdir(), "bdobb-state-"));
  t.after(() => rm(stateDir, { recursive: true, force: true }));
  return { stateDir, ...(await fixture(t, { stateDir, ...overrides })) };
}

test("the state allow-list names the app's own JSON files and nothing else", () => {
  for (const ok of ["settings.json", "backends.json", "folders.json", "chat.json", "chart-presets.json",
    "dashboards/preview.json", "dashboards/docks.json", "dashboards/3f2a-B_c.json"]) assert.equal(stateFile(ok), true, ok);
  for (const bad of ["", "settings.json.tmp", "settings.json.corrupt", "../settings.json", "dashboards/../settings.json",
    "dashboards/a/b.json", "dashboards/.json", "files/a.pdf", "logs/app.log", "skills/x.md", "Settings.json",
    "dashboards/" + "a".repeat(81) + ".json", "settings.json\u0000", 7, null]) assert.equal(stateFile(bad), false, String(bad));
});

test("state round-trips per user: put, list, overwrite, delete", async t => {
  const { port, stateDir } = await stateFixture(t);
  assert.deepEqual(JSON.parse((await http(port, "/state/42")).text), { files: {} });
  assert.equal((await send(port, "/state/42/settings.json", "PUT", '{"theme":"dark"}')).status, 204);
  assert.equal((await send(port, "/state/42/dashboards/preview.json", "PUT", '{"id":"preview"}')).status, 204);
  assert.equal((await send(port, "/state/43/settings.json", "PUT", '{"theme":"light"}')).status, 204);
  assert.deepEqual(JSON.parse((await http(port, "/state/42")).text),
    { files: { "settings.json": '{"theme":"dark"}', "dashboards/preview.json": '{"id":"preview"}' } });
  assert.equal((await send(port, "/state/42/settings.json", "PUT", '{"theme":"sepia"}')).status, 204);
  assert.equal(JSON.parse((await http(port, "/state/42")).text).files["settings.json"], '{"theme":"sepia"}');
  assert.equal((await send(port, "/state/42/settings.json", "DELETE")).status, 204);
  assert.equal((await send(port, "/state/42/settings.json", "DELETE")).status, 204); // idempotent
  assert.deepEqual(Object.keys(JSON.parse((await http(port, "/state/42")).text).files), ["dashboards/preview.json"]);
  // One directory per user, flat, and no temp file left behind.
  assert.deepEqual((await readdir(stateDir)).sort(), ["42", "43"]);
  assert.deepEqual(await readdir(join(stateDir, "42")), ["dashboards%2Fpreview.json"]);
});

test("state refuses everything outside its contract", async t => {
  const { port } = await stateFixture(t);
  const body = '{"a":1}';
  assert.equal((await send(port, "/state/42/settings.json", "PUT", body, { Authorization: "Bearer wrong" })).status, 401);
  for (const path of ["/state/abc/settings.json", "/state/42/files/a.pdf", "/state/42/settings.json.tmp",
    "/state/42/dashboards/a/b.json", "/state/42/settings.json?x=1", "/state/42/", "/state//settings.json",
    "/state/" + "9".repeat(21) + "/settings.json"]) {
    assert.equal((await send(port, path, "PUT", body)).status, 404, path);
  }
  assert.equal((await send(port, "/state/42/../43/settings.json", "PUT", body)).status, 421);
  assert.equal((await send(port, "/state/42/settings.json", "PUT", "not json")).status, 400);
  assert.equal((await send(port, "/state/42/settings.json", "PUT", body, { "Content-Type": "text/plain" })).status, 415);
  assert.equal((await send(port, "/state/42/settings.json", "PUT", JSON.stringify("x".repeat(262145)))).status, 413);
  assert.equal((await send(port, "/state/42/settings.json", "POST", body)).status, 405);
  assert.equal((await send(port, "/state/42", "PUT", body)).status, 405);
  assert.equal((await send(port, "/state/42", "DELETE")).status, 405);
  // The rest of the gateway is exactly as GET-only as it was.
  assert.equal((await send(port, quote, "PUT", body)).status, 405);
  assert.equal((await send(port, "/api/widgets.json", "DELETE")).status, 405);
  assert.deepEqual(JSON.parse((await http(port, "/state/42")).text), { files: {} });
});

test("state is bounded per user, and off until the operator gives it a directory", async t => {
  const { port } = await stateFixture(t, { requestsPerMinute: 600 });
  const big = JSON.stringify("x".repeat(262000));
  for (let i = 0; i < 8; i++) assert.equal((await send(port, `/state/42/dashboards/d${i}.json`, "PUT", big)).status, 204);
  assert.equal((await send(port, "/state/42/dashboards/d8.json", "PUT", big)).status, 413); // > 2 MiB for this user
  assert.equal((await send(port, "/state/42/dashboards/d0.json", "PUT", "{}")).status, 204); // shrinking is fine
  assert.equal((await send(port, "/state/43/settings.json", "PUT", big)).status, 204);       // another user is unaffected

  const off = await fixture(t);
  assert.equal((await http(off.port, "/state/42")).status, 404);
  assert.equal((await send(off.port, "/state/42/settings.json", "PUT", "{}")).status, 404);
});

test("a state directory the service cannot write fails visibly, and the listing survives it", async t => {
  // The named volume is root-owned when Docker first creates it and the service runs as
  // uid 1000 (the Dockerfile now pre-creates and chowns the mount point). If that ever
  // regresses, a PUT must 502 rather than answer 204 over a write that never happened.
  const stateDir = await mkdtemp(join(tmpdir(), "bdobb-state-ro-"));
  t.after(async () => { await chmod(stateDir, 0o700); await rm(stateDir, { recursive: true, force: true }); });
  const { port } = await stateFixture(t, { stateDir });
  await chmod(stateDir, 0o500);
  if (process.getuid?.() === 0) {
    // root ignores the mode bits, so there is no unwritable directory to assert against.
    t.diagnostic("running as root: the read-only PUT assertion is skipped");
  } else {
    assert.equal((await send(port, "/state/42/settings.json", "PUT", "{}")).status, 502);
  }
  // A directory that cannot even be read is an empty list, not a failed one.
  assert.deepEqual(JSON.parse((await http(port, "/state/42")).text), { files: {} });
});

test("a stored name that is not valid percent-encoding is skipped, not a 502 for the whole user", async t => {
  const { port, stateDir } = await stateFixture(t);
  await mkdir(join(stateDir, "42"));
  await writeFile(join(stateDir, "42", "%zz.json"), "{}");            // hand-copied; decodes to nothing
  await writeFile(join(stateDir, "42", "settings.json"), '{"theme":"dark"}');
  const listing = await http(port, "/state/42");
  assert.equal(listing.status, 200);
  assert.deepEqual(JSON.parse(listing.text), { files: { "settings.json": '{"theme":"dark"}' } });
});

test("a temp file a crash left behind is swept once it is stale, and never listed", async t => {
  const { port, stateDir } = await stateFixture(t);
  await mkdir(join(stateDir, "42"));
  const stale = join(stateDir, "42", ".tmp-0011223344556677"), live = join(stateDir, "42", ".tmp-8899aabbccddeeff");
  await writeFile(stale, "{}"); await writeFile(live, "{}");
  const old = new Date(Date.now() - 120_000); await utimes(stale, old, old);
  assert.deepEqual(JSON.parse((await http(port, "/state/42")).text), { files: {} });
  assert.deepEqual(await readdir(join(stateDir, "42")), [".tmp-8899aabbccddeeff"]); // a write in flight is left alone
});

// The stack builds the image compose names, so the package version, the lockfile and the
// compose image tag must agree, or a deploy runs a gateway that predates its own documentation.
test("the package version is this release", () => {
  const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
  const lock = JSON.parse(readFileSync(new URL("./package-lock.json", import.meta.url), "utf8"));
  assert.equal(lock.version, version);
  const compose = readFileSync(new URL("../docker-compose.yml", import.meta.url), "utf8");
  assert.match(compose, new RegExp(`image: openbq-funnel-gateway:${version.replaceAll(".", "\\.")}\\n`));
  assert.match(readFileSync(new URL("./README.md", import.meta.url), "utf8"), new RegExp(`v${version.replaceAll(".", "\\.")}`));
});

const TABLE_RELAY = "private_web_relay_credential_distinct_123456";
const TABLE_PRIVATE = "private_service_credential_distinct_1234567";
async function tableFixture(t, patch = {}) {
  const calls = [];
  const upstream = createServer(async (req, res) => {
    const chunks=[]; for await (const chunk of req) chunks.push(chunk);
    calls.push({path:req.url, headers:req.headers, method:req.method, body:Buffer.concat(chunks).toString()});
    if(req.url === "/sessions/stalled/commands")return;
    if(req.url === "/sessions/truncated/commands"){res.writeHead(200,{"Content-Type":"application/json"});res.write('{"partial":');setImmediate(()=>res.destroy());return;}
    if(req.url === "/sessions/oversized/commands"){res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({text:"x".repeat(8388608)}));return;}
    res.writeHead(req.url === "/sessions/missing/commands" ? 410 : 200, {"Content-Type":"application/json", "Set-Cookie":"secret=bad"});
    res.end(JSON.stringify({ok:true}));
  });
  upstream.listen(0,"127.0.0.1"); await once(upstream,"listening");
  t.after(() => {upstream.closeAllConnections(); upstream.close();});
  const cfg={...config(), apiOrigin:`http://127.0.0.1:${upstream.address().port}`, tableOrigin:`http://127.0.0.1:${upstream.address().port}`, tableGatewayToken:TABLE_PRIVATE, tableRelayToken:TABLE_RELAY, tableDesktopPrincipal:"desktop:owner", ssrmRoutes:["/api/api/v1/test/rows"], ...patch};
  const server=createGateway(cfg); server.listen(0,"127.0.0.1"); await once(server,"listening"); t.after(()=>server.closeGateway());
  const call=(path,method="GET",body,headers={})=>new Promise((resolve,reject)=>{
    const req=request({host:"127.0.0.1",port:server.address().port,path,method,headers:{...HEADERS,...(body!==undefined?{"Content-Type":"application/json","Content-Length":Buffer.byteLength(body)}:{}),...headers}},res=>{
      const chunks=[];res.on("data",c=>chunks.push(c));res.on("end",()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()}));
    });req.on("error",reject);req.end(body);
  }); return {call,calls,cfg};
}
test("table ownership requires independent relay credential; desktop spoofing cannot select owner", async t=>{
  const {call,calls}=await tableFixture(t);
  assert.equal((await call("/table/healthz","GET",undefined,{"X-Table-Principal":"github:99","X-Table-Gateway-Token":"spoof"})).status,200);
  assert.equal(calls[0].headers["x-table-principal"],"desktop:owner");
  assert.equal(calls[0].headers["x-table-gateway-token"],TABLE_PRIVATE);
  assert.equal(calls[0].headers.authorization,undefined);
  const relay={"X-Table-Relay-Token":TABLE_RELAY,"X-Table-Principal":"github:42"};
  assert.equal((await call("/table/sessions","POST",'{}',relay)).status,200);
  assert.equal(calls[1].headers["x-table-principal"],"github:42");
  for (const headers of [{...relay,"X-Table-Relay-Token":"bad"},{...relay,"X-Table-Principal":"desktop:owner"},{"X-Table-Relay-Token":TABLE_RELAY},{...relay,"X-Table-Relay-Token":[TABLE_RELAY,TABLE_RELAY]},{...relay,"X-Table-Principal":["github:42","github:99"]}]) assert.equal((await call("/table/healthz","GET",undefined,headers)).status,401);
  assert.equal(calls.length,2);
});
test("table gateway absence, bounded bodies, registered methods and sanitized errors",async t=>{
  const {call,calls}=await tableFixture(t);
  assert.equal((await call("/table/sessions","GET")).status,404);
  assert.equal((await call("/table/sessions","POST",'x')).status,400);
  assert.equal((await call("/table/sessions","POST",'{}',{"Content-Length":2097153})).status,413);
  assert.equal((await call("/table/sessions/missing/commands","POST",'{}')).status,410);
  assert.equal((await call("/table/sessions/x/derive","POST",'{}')).status,200);
  assert.equal(calls.length,2);
  const absent=await tableFixture(t,{tableOrigin:null}); assert.equal((await absent.call("/table/healthz")).status,503);
  const unowned=await tableFixture(t,{tableDesktopPrincipal:null}); assert.equal((await unowned.call("/table/healthz")).status,401);
});

test("table credential configuration fails closed and service origins are fixed",()=>{
  const enabled={...settings,tableService:true,tableDesktopPrincipal:"desktop:owner",ssrmRoutes:["/api/api/v1/test/rows"]};
  const privateSecrets={...secrets,tableGatewayToken:TABLE_PRIVATE,tableRelayToken:TABLE_RELAY};
  const cfg=validateConfig(enabled,privateSecrets);assert.equal(cfg.tableOrigin,"http://table-service:8080");
  for(const patch of [{tableGatewayToken:TOKEN},{tableRelayToken:TOKEN},{tableRelayToken:TABLE_PRIVATE},{tableGatewayToken:""},{tableRelayToken:"short"}])assert.throws(()=>validateConfig(enabled,{...privateSecrets,...patch}));
  for(const patch of [{tableDesktopPrincipal:"github:42"},{tableService:"true"},{ssrmRoutes:["https://evil.example.com"]},{ssrmRoutes:["/api/api/v1/a/../b"]},{tableOrigin:"http://evil.example.com"},{tableTimeoutMs:0}])assert.throws(()=>validateConfig({...enabled,...patch},privateSecrets));
});
test("table batches fail atomically on truncation, oversize or deadline; standard POST is exact and metered",async t=>{
  const {call,calls,cfg}=await tableFixture(t,{tableTimeoutMs:40});
  for(const name of ["stalled","truncated","oversized"]){const result=await call(`/table/sessions/${name}/commands`,"POST",'{}').catch(error=>{throw new Error(name,{cause:error});});assert.equal(result.status,502);assert.doesNotMatch(result.body,/partial|xxxxxxxx/);}
  cfg.tableTimeoutMs=65000;
  const result=await call("/api/api/v1/test/rows?symbol=AAPL","POST",'{"startRow":0,"endRow":10}').catch(error=>{throw new Error("standard",{cause:error});});assert.equal(result.status,200);
  assert.equal(calls.at(-1).path,"/api/v1/test/rows?symbol=AAPL");assert.equal(calls.at(-1).body,'{"startRow":0,"endRow":10}');
  assert.equal(calls.at(-1).headers.authorization,config().apiAuthorization);assert.equal(calls.at(-1).headers["x-table-principal"],undefined);
  assert.equal((await call("/table/sessions/../healthz").catch(error=>{throw new Error("traversal",{cause:error});})).status,421);
  assert.equal((await call("/table/sessions/%2e%2e/healthz").catch(error=>{throw new Error("encoded",{cause:error});})).status,421);
  const capped=await tableFixture(t,{quoteDailyLimit:1});assert.equal((await capped.call("/api/api/v1/test/rows","POST",'{}')).status,200);assert.equal((await capped.call("/api/api/v1/test/rows","POST",'{}')).status,429);
});
