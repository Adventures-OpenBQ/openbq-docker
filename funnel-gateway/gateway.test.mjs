// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { socketTicket, stateFile } from "./policy.mjs";
import { chmod, mkdtemp, mkdir, readdir, rm, utimes, writeFile } from "node:fs/promises";
import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter, once } from "node:events";
import { createServer, request } from "node:http";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import { validateConfig, readConfig } from "./config.mjs";
import { createGateway, getJson, connectGrid, subscriptionRoute, rewriteGridWidgets } from "./server.mjs";
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
// live-grid (the `live` profile, v10) is ON in the default fixture too, so the /grid tests
// ported from the donor run as written; the off state (503) has its own tests.
const settings = { origin: ORIGIN, quoteDailyLimit: 100,
  rssOrigin: RSS_ORIGIN, rssAddress: RSS_ADDRESS, feeds: { [FEED]: 7 }, liveGrid: true };
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
  // live-grid is a fixed compose service name too, not an operator setting -- which is why
  // the matrix below still refuses a settings file that names `gridOrigin`. The fixture turns
  // the `live` profile on ("liveGrid": true); the off state has its own test below.
  assert.equal(config().gridOrigin, "http://live-grid:6903");
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
    { maxConcurrent: 0 }, { maxConcurrent: 33 },
    { maxSockets: 0 }, { maxSockets: 33 }, { maxSockets: 1.5 }, { maxSockets: "4" },
    // The preview origin is any HTTPS origin (a Vercel name is not on the tailnet), but only an origin.
    { previewOrigin: "http://bdobb.example.vercel.app" }, { previewOrigin: "https://bdobb.example.vercel.app/x" },
    { previewOrigin: "https://user@bdobb.example.vercel.app" }, { previewOrigin: "https://bdobb.example.vercel.app:8443" },
    // A Vercel origin is portless: not even the door's own 10000 is accepted.
    { previewOrigin: "https://bdobb.example.vercel.app:10000" },
    { previewOrigin: null }, { previewOrigin: "" }, { previewOrigin: 7 },
    { stateDir: "relative/state" }, { stateDir: "/var/lib/../etc" }, { stateDir: 7 }, { stateDir: "" },
    // Not silently accepted: `tickUrl` is a later line's upstream, and `gridOrigin` is THIS
    // line's but is fixed in code rather than configured -- naming either in settings.json
    // means an operator believes something is configurable that is not. `liveGrid` is a
    // boolean and nothing else.
    { gridOrigin: "http://openbb-live-grid:6903" }, { gridOrigin: "http://live-grid:6903" },
    { tickUrl: `wss://kdb.${TAILNET}` }, { liveGrid: "true" }, { liveGrid: 1 }, { liveGrid: null },
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
  assert.equal(validateConfig({ ...settings, previewOrigin: "https://BDOBB.example.vercel.app" }, secrets).previewOrigin,
    "https://bdobb.example.vercel.app");
  assert.deepEqual([1, 32].map(maxSockets => validateConfig({ ...settings, maxSockets }, secrets).maxSockets), [1, 32]);
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

// The packaged desktop app's webview origins on /api (user ruling 2026-10-15: the HTTP half of V10-P1
// moved down to v4 with the gateway). DESKTOP is declared with the V10-P1 tests below.
test("the packaged desktop origins pass the Bearer lock on /api; nothing else new does", async t => {
  const { port } = await fixture(t);
  for (const origin of DESKTOP) {
    assert.equal((await http(port, quote, { ...HEADERS, Origin: origin })).status, 200, origin);
    // The Origin is never a credential: without the Bearer token it is what it always was.
    assert.equal((await http(port, quote, { Host: HEADERS.Host, Origin: origin })).status, 401, origin);
  }
  // The dev server's origin is not a packaged app's, and is not admitted.
  assert.equal((await http(port, quote, { ...HEADERS, Origin: "http://localhost:1420" })).status, 403);
});

test("only bounded OpenBB and approved News queries reach upstream; later families are refused", async t => {
  const { port, calls } = await fixture(t);
  for (const path of ["/", "/tick", "/keys", "/mcp", "/stores", "/live/widgets.json",
    quote + "&symbol=MSFT",
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

test("a reference GET forwards with no credential; Omni and unlisted dotted paths 404; a down reference is 502", async t => {
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ url: req.url, headers: req.headers });
    if (req.url === "/assets/bdobb-logo.svg") {
      res.writeHead(200, { "Content-Type": "image/svg+xml" }); return res.end("<svg/>");
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end('{"ok":true}');
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { refOrigin: `http://127.0.0.1:${upstream.address().port}` }, { requestJson: getJson });
  const ok = await http(port, "/ref/metric_widget?x=1", { ...HEADERS, Origin: ORIGIN, Cookie: "viewer=session" });
  assert.equal(ok.status, 200);
  assert.equal(ok.text, '{"ok":true}');
  assert.equal(seen[0].url, "/metric_widget?x=1");
  assert.equal(seen[0].headers.authorization, undefined);
  assert.equal(seen[0].headers.cookie, undefined);
  for (const bad of ["/ref/omni-sql-widget", "/ref/assets/other.svg", "/ref/metric_widget.json", "/ref/data/"]) {
    assert.equal((await http(port, bad)).status, 404, bad);
  }
  assert.equal((await http(port, "/ref/metric_widget", HEADERS, "POST")).status, 405);
  const logo = await http(port, "/ref/assets/bdobb-logo.svg");
  assert.equal(logo.status, 200);
  assert.equal(logo.text, "<svg/>");
  assert.equal(logo.headers["content-type"], "image/svg+xml");
  assert.equal(logo.headers["x-content-type-options"], "nosniff");
  assert.match(logo.headers["content-security-policy"], /sandbox/);
  assert.equal(logo.headers["x-robots-tag"], "noindex, nofollow, noarchive");
  assert.equal(logo.headers["cache-control"], "no-store");
  // The logo takes the same Origin rule as JSON: a foreign Origin is 403.
  assert.equal((await http(port, "/ref/assets/bdobb-logo.svg", { ...HEADERS, Origin: "https://evil.invalid" })).status, 403);
  // Nothing reaches a host other than the fixture: "//host" paths are refused before any request,
  // and the upstream URL is built by concatenation (a recording requestJson would see no call).
  const before = seen.length;
  for (const bad of ["/ref//omni-sql-widget", "/ref//openbq-api/api/v1/x", "/ref/data//x"]) {
    assert.equal((await http(port, bad)).status, 404, bad);
  }
  assert.equal(seen.length, before);
  assert.equal(seen.length, 2);
  // Even if policy were bypassed, getJson resolves "//host" against the fixed origin by concatenation.
  const direct = { refOrigin: `http://127.0.0.1:${upstream.address().port}` };
  assert.deepEqual(await getJson("/ref//openbq-api/x", direct), { ok: true });
  assert.equal(seen.at(-1).url, "//openbq-api/x");
  assert.deepEqual(await getJson("/api//openbq-api/x", { apiOrigin: direct.refOrigin, apiAuthorization: "Basic x" }), { ok: true });
  assert.equal(seen.at(-1).url, "//openbq-api/x");
  // A down reference: the door's own refusal, never the upstream's.
  const dead = createServer(); dead.listen(0, "127.0.0.1"); await once(dead, "listening");
  const deadPort = dead.address().port; await new Promise(resolve => dead.close(resolve));
  const down = await fixture(t, { refOrigin: `http://127.0.0.1:${deadPort}` }, { requestJson: getJson });
  const gone = await http(down.port, "/ref/metric_widget");
  assert.equal(gone.status, 502);
  assert.equal(gone.text, '{"error":"Request refused"}');
  // A reference that accepts and never answers: the request deadline aborts it, still a 502.
  const hung = createServer(() => {}); hung.listen(0, "127.0.0.1"); await once(hung, "listening");
  t.after(() => { hung.closeAllConnections(); return new Promise(resolve => hung.close(resolve)); });
  const stuck = await fixture(t, { refOrigin: `http://127.0.0.1:${hung.address().port}` },
    { requestJson: getJson, requestMs: 200 });
  const timedOut = await http(stuck.port, "/ref/metric_widget");
  assert.equal(timedOut.status, 502);
  assert.equal(timedOut.text, '{"error":"Request refused"}');
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

test("root manifests get MANIFEST_MAX (16 MiB); every other path keeps 2 MiB", async t => {
  // openbq-api's widgets.json measured 5.0 MB (998 widgets) on 2026-10-15, past the 2 MiB
  // every other body is held to. Over either cap, getJson destroys the response and the
  // caller sees an honest 502, never a document silently cut in half.
  let size = 5_000_000;
  const upstream = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(Object.fromEntries(
      Array.from({ length: 400 }, (_, i) => [`w${i}`, "x".repeat(Math.ceil(size / 400))]))));
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const origin = `http://127.0.0.1:${upstream.address().port}`;
  const { port } = await fixture(t, { apiOrigin: origin, refOrigin: origin }, { requestJson: getJson });
  for (const path of ["/api/widgets.json", "/api/apps.json", "/ref/widgets.json", "/ref/apps.json"]) {
    const ok = await http(port, path);
    assert.equal(ok.status, 200, path);
    assert.equal(Object.keys(JSON.parse(ok.text)).length, 400);
  }
  // The same ~5 MB on a DATA route is still past MAX_BODY.
  assert.equal((await http(port, quote)).status, 502);
  size = 2 * 1024 * 1024 + 1024;
  assert.equal((await http(port, quote)).status, 502);
  size = 16 * 1024 * 1024 + 1024;
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

/**
 * live-grid's own leg of the preflight, as a loopback fixture: it answers /health, behind the
 * SAME Basic pair as openbb-api (its BasicAuthMiddleware wraps its whole app, /health
 * included), and records what it was asked. `grid.status` lets a test make it fail.
 */
async function gridStub(t) {
  const grid = { status: 200, seen: [] };
  const server = createServer((req, res) => {
    grid.seen.push({ path: req.url, auth: req.headers.authorization });
    res.writeHead(grid.status, { "Content-Type": "application/json" }); res.end("{}");
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  grid.origin = `http://127.0.0.1:${server.address().port}`;
  return grid;
}

test("upstream preflight validates Basic auth and the API's lock without querying a quote", async t => {
  let withPair = 422, withoutPair = 401;
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ path: req.url, auth: req.headers.authorization });
    res.writeHead(req.headers.authorization ? withPair : withoutPair); res.end();
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const grid = await gridStub(t);
  // The wire is left OUT of this config: what is under test is the API leg, and the wire's
  // own preflight has its own test below (it would otherwise dial a real tailnet address).
  const cfg = { ...config(), rssOrigin: null, rssAddress: null, feeds: {},
    apiOrigin: `http://127.0.0.1:${upstream.address().port}`, gridOrigin: grid.origin };
  await checkUpstreams(cfg);
  // openbq-api serves the quote only under /api/v1/eodhd/; that path is asked first, and it
  // answered, so the standard path is never dialled.
  assert.deepEqual(seen, [{ path: "/api/v1/eodhd/equity/price/quote", auth: cfg.apiAuthorization },
    { path: "/api/v1/eodhd/equity/price/quote", auth: undefined }]);
  withPair = 401; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  withPair = 200; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  // OPENBB_API_AUTH off: the pair is "accepted" because nothing is checked. The door stays shut.
  withPair = 422; withoutPair = 422; await assert.rejects(checkUpstreams(cfg), /API lock preflight failed/);
});

test("upstream preflight falls back to the standard quote route only on a 404, and fails on two", async t => {
  // A stack whose API has no EODHD extension: /api/v1/eodhd/... is 404 with the pair.
  let standard = true;
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ path: req.url, auth: req.headers.authorization });
    const known = standard && req.url === "/api/v1/equity/price/quote";
    res.writeHead(!req.headers.authorization ? 401 : known ? 422 : 404); res.end();
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const cfg = { ...config(), rssOrigin: null, rssAddress: null, feeds: {}, gridOrigin: null,
    apiOrigin: `http://127.0.0.1:${upstream.address().port}` };
  await checkUpstreams(cfg);
  // The lock is proved on the path that answered, not on the 404.
  assert.deepEqual(seen, [
    { path: "/api/v1/eodhd/equity/price/quote", auth: cfg.apiAuthorization },
    { path: "/api/v1/equity/price/quote", auth: cfg.apiAuthorization },
    { path: "/api/v1/equity/price/quote", auth: undefined }]);
  // Neither route served: the 404 that stopped the old preflight still stops this one, and
  // the message names the last path asked.
  standard = false;
  await assert.rejects(checkUpstreams(cfg),
    /API auth preflight failed \(HTTP 404 on \/api\/v1\/equity\/price\/quote\)/);
});

test("upstream preflight does not fall back past a refusal on the EODHD route", async t => {
  // 401 on the first path is a wrong pair, not a missing route: it stops at once.
  const seen = [];
  const upstream = createServer((req, res) => { seen.push(req.url); res.writeHead(401); res.end(); });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const cfg = { ...config(), rssOrigin: null, rssAddress: null, feeds: {}, gridOrigin: null,
    apiOrigin: `http://127.0.0.1:${upstream.address().port}` };
  await assert.rejects(checkUpstreams(cfg), /API auth preflight failed \(HTTP 401 on \/api\/v1\/eodhd\//);
  assert.deepEqual(seen, ["/api/v1/eodhd/equity/price/quote"]);
});

test("the preflight proves live-grid answers /health behind the stack's own Basic pair", async t => {
  // A locked API (422 with the pair, 401 without): openbq-docker's preflight also proves the lock.
  const api = createServer((req, res) => { res.writeHead(req.headers.authorization ? 422 : 401); res.end(); });
  api.listen(0, "127.0.0.1"); await once(api, "listening");
  t.after(() => new Promise(resolve => api.close(resolve)));
  const grid = await gridStub(t);
  const cfg = { ...config(), rssOrigin: null, rssAddress: null, feeds: {},
    apiOrigin: `http://127.0.0.1:${api.address().port}`, gridOrigin: grid.origin };
  await checkUpstreams(cfg);
  // Asked for /health and nothing else, WITH the credential. Without it live-grid answers
  // 401 and the preflight would stop a healthy stack from opening its door -- which is the
  // whole reason this leg carries the pair.
  assert.deepEqual(grid.seen, [{ path: "/health", auth: cfg.apiAuthorization }]);
  // Anything but a 200 stops the door: 401 (the pair is wrong or absent) and 503 (live-grid
  // is up but not ready) are both refusals, not warnings.
  for (const status of [401, 503, 500]) {
    grid.status = status;
    await assert.rejects(checkUpstreams(cfg), new RegExp(`live-grid preflight failed \\(HTTP ${status}\\)`));
  }
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
  const grid = await gridStub(t);
  const cfg = { ...config(), apiOrigin: `http://127.0.0.1:${api.address().port}`,
    gridOrigin: grid.origin,
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

// ---- The desktop app (V10-P1, user ruling 2026-10-15). Its HTTP goes through Tauri's http
// plugin, which stamps the webview's Origin on every request; its socket is the webview's own.
const DESKTOP = ["tauri://localhost", "http://tauri.localhost"];
const mint = (port, target, origin) =>
  http(port, "/grid/ws_ticket?target=" + encodeURIComponent(target), { ...HEADERS, Origin: origin });

test("the packaged desktop origins pass the Bearer lock on HTTP; nothing else new does", async t => {
  const { port } = await fixture(t);
  for (const origin of DESKTOP) {
    assert.equal((await http(port, "/grid/widgets.json", { ...HEADERS, Origin: origin })).status, 200, origin);
    // The Origin is never a credential: without the Bearer token it is what it always was.
    assert.equal((await http(port, "/grid/widgets.json", { Host: HEADERS.Host, Origin: origin })).status, 401, origin);
  }
  // The dev server's origin is not a packaged app's, and is not admitted.
  assert.equal((await http(port, "/grid/widgets.json", { ...HEADERS, Origin: "http://localhost:1420" })).status, 403);
});

test("the desktop mints a ticket bound to its Origin and the socket, and opens the socket on it once", async t => {
  const { port } = await fixture(t);
  const path = "/grid/live_grid_ws";
  const answer = await mint(port, path, DESKTOP[0]);
  assert.equal(answer.status, 200);
  assert.equal(answer.headers["cache-control"], "no-store");
  const { ticket } = JSON.parse(answer.text);
  // Bound to the Origin that asked: the other packaged origin cannot spend it.
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: DESKTOP[1] }, ticketed(path, ticket))).status, 401);
  const opened = await wsConnect(port, { Host: HEADERS.Host, Origin: DESKTOP[0] }, ticketed(path, ticket));
  assert.equal(opened.status, 101); opened.ws.terminate();
  // Single use, like the preview's.
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: DESKTOP[0] }, ticketed(path, ticket))).status, 401);
  // Bound to the target: a grid ticket opens nothing else.
  const other = JSON.parse((await mint(port, path, DESKTOP[1])).text).ticket;
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: DESKTOP[1] }, ticketed("/news/ws/news", other))).status, 401);
  // A preview-shaped ticket (signed over the target alone) is not a desktop ticket, and a
  // desktop ticket is not a preview ticket.
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: DESKTOP[0] },
    ticketed(path, socketTicket(TOKEN, path)))).status, 401);
  const preview = await fixture(t, { previewOrigin: PREVIEW });
  const desktopTicket = JSON.parse((await mint(preview.port, path, DESKTOP[0])).text).ticket;
  assert.equal((await wsConnect(preview.port, browser, ticketed(path, desktopTicket))).status, 401);
});

test("the mint endpoint is locked, desktop-only, and signs only a /grid socket", async t => {
  const { port } = await fixture(t);
  assert.equal((await http(port, "/grid/ws_ticket?target=%2Fgrid%2Flive_grid_ws",
    { Host: HEADERS.Host, Origin: DESKTOP[0] })).status, 401);
  // A caller with no desktop Origin holds the Bearer token and opens the socket with it.
  assert.equal((await http(port, "/grid/ws_ticket?target=%2Fgrid%2Flive_grid_ws")).status, 403);
  assert.equal((await mint(port, "/grid/live_grid_ws", ORIGIN)).status, 403);
  for (const target of ["/news/ws/news", "/grid/live_grid_ws?x=1", "/grid/live_grid", "/nope", "//evil/grid/live_grid_ws"]) {
    assert.equal((await mint(port, target, DESKTOP[0])).status, 404, target);
  }
  assert.equal((await http(port, "/grid/ws_ticket?target=%2Fgrid%2Flive_grid_ws&target=x",
    { ...HEADERS, Origin: DESKTOP[0] })).status, 404);
});

// ---- The wire's socket: the first route this door serves over a socket (Ep. 8).

test("the WS gate wants the credential, the Origin, the exact path and a configured wire", async t => {
  const { port } = await fixture(t, {}, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  // Nothing in this test reaches an upstream: every assertion below is a refusal.
  assert.equal((await wsConnect(port, { Host: HEADERS.Host, Origin: ORIGIN })).status, 401);
  assert.equal((await wsConnect(port, HEADERS)).status, 403);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: "https://untrusted.invalid" })).status, 403);
  // The desktop Origins pass on HTTP only; their sockets wait for v10's ticket (V10-P1).
  for (const origin of DESKTOP) assert.equal((await wsConnect(port, { ...HEADERS, Origin: origin })).status, 403, origin);
  // The socket takes no query and no subprotocol, and no other path is a socket at all.
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/news/ws/news?admin=1")).status, 404);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/grid/live_grid_ws?symbol=AAPL")).status, 404);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/grid/ta_series_ws")).status, 404);
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
  for (const path of ["/news/ws/news?x=1", "/grid/live_grid_ws?x=1", "/grid/ta_chart_ws", "/nope"]) {
    assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
  }
  const admitted = await wsConnect(port); assert.equal(admitted.status, 101); admitted.ws.terminate();
});

// ---- The grid family (Ep. 10): live-grid's REST surface and its socket, the second socket
// route this door serves and the first whose frames repeat.

const GRID_WS = "/grid/live_grid_ws";
const gridConnect = (f, headers) => wsConnect(f.port, headers, GRID_WS);

test("the grid's REST routes reach live-grid with the prefix stripped and the stack's pair", async t => {
  const seen = [];
  const upstream = createServer((req, res) => {
    seen.push({ url: req.url, headers: req.headers });
    res.writeHead(200, { "Content-Type": "application/json", "Set-Cookie": "sensitive=test" });
    res.end('{"rows":[]}');
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { gridOrigin: `http://127.0.0.1:${upstream.address().port}` },
    { requestJson: getJson });
  const response = await http(port, "/grid/live_grid?symbol=AAPL,MSFT",
    { ...HEADERS, Cookie: "viewer=session", "X-Forwarded-For": "untrusted" });
  assert.equal(response.status, 200);
  assert.equal(response.headers["set-cookie"], undefined);
  // "/grid" and nothing else is stripped -- live-grid's own route is /live_grid.
  assert.equal(seen[0].url, "/live_grid?symbol=AAPL%2CMSFT");
  // The pair live-grid's own BasicAuthMiddleware demands, and none of the caller's headers.
  assert.equal(seen[0].headers.authorization, config().apiAuthorization);
  assert.equal(seen[0].headers.accept, "application/json");
  assert.equal(seen[0].headers.cookie, undefined);
  assert.equal(seen[0].headers["x-forwarded-for"], undefined);
  assert.ok(!response.text.includes(TOKEN));
  // The manifest keeps its own name, and the chart's theme rides through re-serialised.
  assert.equal((await http(port, "/grid/widgets.json")).status, 200);
  assert.equal(seen[1].url, "/widgets.json");
  assert.equal((await http(port, "/grid/chart?symbol=AAPL&interval=1d&theme=dark")).status, 200);
  assert.equal(seen[2].url, "/chart?symbol=AAPL&interval=1d&theme=dark");
  assert.equal((await http(port, "/grid/live_grid?symbol=AAPL")).status, 200);
  // The kdb tick reader, this line's own route: "/grid" and nothing else stripped, limit
  // re-serialised from the parsed pair.
  assert.equal((await http(port, "/grid/ticks?symbol=AAPL&limit=50")).status, 200);
  assert.equal(seen[4].url, "/ticks?symbol=AAPL&limit=50");
  assert.equal(seen[4].headers.authorization, config().apiAuthorization);
  // The tick chart's REST leg, this line's own route: the query is re-serialised from the
  // validated pairs, so what live-grid sees is the door's encoding and not the caller's.
  assert.equal((await http(port, "/grid/ta_chart?symbol=NVDA&indicators=rsi:period=14&theme=dark")).status, 200);
  assert.equal(seen[5].url, "/ta_chart?symbol=NVDA&indicators=rsi%3Aperiod%3D14&theme=dark");
  assert.equal(seen[5].headers.authorization, config().apiAuthorization);
  assert.equal(seen.length, 6);
});

test("the daily vendor cap covers the grid's data routes, out of the SAME counter as /api", async t => {
  // /grid/live_grid calls the EODHD SDK once per symbol in the watchlist
  // (live-grid/app/quotes.py), and /grid/series and /grid/chart both run build_series ->
  // fetch_series -> openbb-api /api/v1/equity/price/historical with provider=kdb|eodhd
  // (live-grid/app/openbb_client.py) -- the same paid upstream /api/api/v1/** is metered for
  // reaching. A DELIBERATE deviation from main, which meters none of them (review ruling
  // 2026-09-26): otherwise the door's daily vendor cap is bypassable through /grid at the
  // full per-minute rate, and EODHD quota exhaustion surfaces as stack-wide 502s.
  for (const metered of ["/grid/live_grid?symbol=AAPL", "/grid/symbol_meta?symbol=AAPL",
    "/grid/series?symbol=AAPL", "/grid/chart?symbol=AAPL", "/grid/ta_chart?symbol=AAPL"]) {
    const { port } = await fixture(t, { quoteDailyLimit: 1 });
    assert.equal((await http(port, metered)).status, 200, metered);
    assert.equal((await http(port, metered)).status, 429, metered);
    // ONE counter, not a second grid-only budget: the /api quote is refused by the unit the
    // grid call just spent.
    assert.equal((await http(port, quote)).status, 429, metered);
  }
  // And the other direction: an /api quote spends the unit a grid call then cannot have.
  const shared = await fixture(t, { quoteDailyLimit: 1 });
  assert.equal((await http(shared.port, quote)).status, 200);
  assert.equal((await http(shared.port, "/grid/series?symbol=AAPL")).status, 429);
  // Unmetered, for the same reason /api's two manifests are: no provider is called for a
  // document, and /grid/ticks reads the in-memory kdb cache. Four of them do not exhaust a
  // budget of one. (/grid/symbol_meta is NOT on this list on this line -- its route exists
  // here and calls get_fundamentals_data per uncached symbol.)
  const { port } = await fixture(t, { quoteDailyLimit: 1 });
  for (const free of ["/grid/widgets.json", "/grid/apps.json", "/grid/ticks?symbol=AAPL",
    "/grid/ticks?symbol=AAPL&limit=1000", "/grid/widgets.json"])
    assert.equal((await http(port, free)).status, 200, free);
  assert.equal((await http(port, "/grid/chart?symbol=AAPL")).status, 200);
  assert.equal((await http(port, "/grid/live_grid?symbol=AAPL")).status, 429);
});

test("the grid's optional documents relay a bare 404; every other non-200 is the door's 502", async t => {
  // dataClient fetches apps.json and symbol_meta with `allow404` and matches on the literal
  // status, so the door's own 502 would make fetchAppsJson THROW where it is built to resolve
  // "this backend ships no apps". This line's live-grid really serves both, so the relay is
  // the OLDER-UPSTREAM fallback -- which is exactly what this fixture models, and why the
  // route keeps it. The status is relayed; nothing else about the answer is.
  let status = 404;
  const upstream = createServer((_, res) => {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end('{"detail":"Not Found","upstream":"live-grid"}');
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { gridOrigin: `http://127.0.0.1:${upstream.address().port}` },
    { requestJson: getJson });
  for (const optional of ["/grid/apps.json", "/grid/symbol_meta?symbol=AAPL"]) {
    const response = await http(port, optional);
    assert.equal(response.status, 404, optional);
    // The door's OWN body: live-grid's document never reaches the caller.
    assert.deepEqual(JSON.parse(response.text), { error: "Request refused" });
  }
  // A 404 on any OTHER route is still the door's 502 -- widgets.json is required, and a
  // missing grid seed or tick answer is a broken upstream, not an answer.
  assert.equal((await http(port, "/grid/widgets.json")).status, 502);
  assert.equal((await http(port, "/grid/live_grid?symbol=AAPL")).status, 502);
  assert.equal((await http(port, "/grid/ticks?symbol=AAPL")).status, 502);
  // And only the 404 is relayed: the same optional document behind a 500 is a 502.
  status = 500;
  assert.equal((await http(port, "/grid/apps.json")).status, 502);
});

/** A live-grid socket fixture, shaped exactly like the wire's: cap of one, a queue of
 *  upstream connections, and the grid's own opener injected. */
async function gridFixture(t, overrides = {}) {
  const grid = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(grid, "listening");
  const nextConnection = connectionQueue(grid);
  t.after(() => new Promise(resolve => {
    for (const ws of grid.clients) ws.terminate(); grid.close(resolve);
  }));
  const gw = await fixture(t, { maxSockets: 1, ...overrides },
    { openGrid: () => new WebSocket(`ws://127.0.0.1:${grid.address().port}`) });
  return { ...gw, nextConnection };
}
/** A live grid relay: a client through the door, its first params frame sent, and the
 *  live-grid side of the connection that frame caused. */
async function gridRelayed(f, symbol = "AAPL") {
  const { ws } = await gridConnect(f);
  ws.send(JSON.stringify({ params: { symbol } }));
  // BOUNDED. nextConnection() never rejects, so a regression that stops the first frame
  // opening the upstream -- a budget refusal charged where it should not be, say -- would
  // hang the whole suite instead of failing it. Same reason every teardown assertion here
  // goes through within(), and it fails naming what never came.
  let timer;
  const up = await Promise.race([
    f.nextConnection().finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("live-grid was never dialled within 2000ms")), 2000);
    }),
  ]);
  return { ws, up };
}
/** The grid's slot is back: with maxSockets at 1, a second grid socket only opens if the
 *  first was released. */
async function gridSlotReleased(f) {
  const again = await gridConnect(f);
  assert.equal(again.status, 101, "the socket slot was not released");
  again.ws.terminate();
}

test("the grid socket relays a rebuilt params frame, and a REPEAT frame is forwarded, not fatal", async t => {
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  const frames = [];
  up.on("message", data => frames.push(JSON.parse(data)));
  const first = within(up, "message");
  up.send('{"type":"quote"}');
  assert.equal((await within(ws, "message"))[0].toString(), '{"type":"quote"}');
  await first;
  // The parameter change the wire's socket could never accept: a SECOND frame over the same
  // open socket, re-validated and forwarded rather than closing the relay. This is the whole
  // difference between liveGridSubscription and newsSubscription.
  const second = within(up, "message");
  ws.send(JSON.stringify({ params: { symbol: "TSLA,NVDA" } }));
  await second;
  assert.deepEqual(frames, [{ params: { symbol: "AAPL" } }, { params: { symbol: "TSLA,NVDA" } }]);
  // Still one upstream connection: a repeat frame reuses the one the first frame opened.
  assert.equal(ws.readyState, WebSocket.OPEN);
  // And a frame OUTSIDE the contract still closes it, however many valid ones came before.
  const closed = within(ws, "close");
  ws.send(JSON.stringify({ params: { symbol: "AAPL", admin: true } }));
  await closed;
  await gridSlotReleased(f);
});

test("only the newest params frame is held while live-grid's handshake is in flight", async t => {
  // The frames are sent before the upstream is open, so they take the pending path. A
  // `once(\"open\")` listener per frame would forward all three and grow one closure per
  // frame; one pending frame means live-grid is told the newest state once.
  const grid = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(grid, "listening");
  t.after(() => new Promise(resolve => { for (const c of grid.clients) c.terminate(); grid.close(resolve); }));
  const frames = [];
  grid.on("connection", up => up.on("message", data => frames.push(JSON.parse(data))));
  const { port } = await fixture(t, {},
    { openGrid: () => new WebSocket(`ws://127.0.0.1:${grid.address().port}`) });
  const { ws } = await gridConnect({ port });
  for (const symbol of ["AAPL", "MSFT", "TSLA"]) ws.send(JSON.stringify({ params: { symbol } }));
  // One frame, and it is the last one sent -- a params frame is the client's whole state,
  // not a delta, so superseding is also what live-grid needs to be told.
  await within(grid, "connection").catch(() => {});
  for (let i = 0; i < 20 && frames.length < 1; i++) await new Promise(r => setTimeout(r, 25));
  assert.deepEqual(frames, [{ params: { symbol: "TSLA" } }]);
  ws.terminate();
});

test("a params frame outside the contract never opens live-grid", async t => {
  let opened = 0;
  const { port } = await fixture(t, {}, { openGrid: () => { opened++; throw new Error("Must not connect"); } });
  for (const frame of ["not-json", '{"params":{}}', '{"params":{"symbol":""}}',
    JSON.stringify({ params: { symbol: "AAPL" }, admin: true }),
    JSON.stringify({ params: { symbol: "AAPL;DROP TABLE" } }),
    JSON.stringify({ subscribe: [{ url: FEED }] }),   // the wire's frame is not this one's
    Buffer.from("binary"), "x".repeat(65537)]) {
    const { ws } = await gridConnect({ port }); const closed = once(ws, "close");
    ws.send(frame); await closed;
  }
  assert.equal(opened, 0);
});

test("live-grid closing tears down the grid client, and hands the slot back", async t => {
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  const closed = within(ws, "close");
  up.close();
  await closed;
  await gridSlotReleased(f);
});

test("a grid client going away terminates live-grid's connection, and hands the slot back", async t => {
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  const upClosed = within(up, "close");
  ws.terminate();
  await upClosed;
  await gridSlotReleased(f);
});

test("a grid client too far behind is closed rather than queued behind, and hands the slot back", async t => {
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  // Same reasoning as the wire's version: `client.bufferedAmount` is read off the
  // server-side socket inside createGateway, so the getter is stubbed for this one send
  // rather than a test-only handle added to the server. Restored immediately and in t.after.
  const real = Object.getOwnPropertyDescriptor(WebSocket.prototype, "bufferedAmount");
  const restore = () => Object.defineProperty(WebSocket.prototype, "bufferedAmount", real);
  t.after(restore);
  Object.defineProperty(WebSocket.prototype, "bufferedAmount", { configurable: true, get: () => 262145 });
  const closed = within(ws, "close");
  up.send('{"type":"quote"}');
  await closed;
  restore();
  await gridSlotReleased(f);
});

test("a grid client outrunning live-grid is closed rather than queued upstream, and hands the slot back", async t => {
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  // The mirror of the test above, on the direction this row introduced: a params frame per
  // parameter change for the socket's whole lifetime, against a live-grid that is not
  // draining. `upstream.bufferedAmount` is read off the gateway's own client socket inside
  // createGateway, so the prototype getter is stubbed for this one frame rather than a
  // test-only handle added to the server. Restored immediately and in t.after.
  const real = Object.getOwnPropertyDescriptor(WebSocket.prototype, "bufferedAmount");
  const restore = () => Object.defineProperty(WebSocket.prototype, "bufferedAmount", real);
  t.after(restore);
  Object.defineProperty(WebSocket.prototype, "bufferedAmount", { configurable: true, get: () => 262145 });
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  ws.send(JSON.stringify({ params: { symbol: "TSLA" } }));
  await closed;
  await upClosed;
  restore();
  await gridSlotReleased(f);
});

test("an oversized or binary frame from live-grid closes the relay, and hands the slot back", async t => {
  for (const [what, send] of [
    ["oversized", up => up.send("x".repeat(65537))],
    ["binary", up => up.send(Buffer.from("quote"), { binary: true })],
  ]) {
    const f = await gridFixture(t);
    const { ws, up } = await gridRelayed(f);
    const closed = within(ws, "close", 2000);
    send(up);
    await closed.catch(error => { throw new Error(`${what}: ${error.message}`); });
    await gridSlotReleased(f);
  }
});

test("EVERY grid params frame charges the daily counter once per symbol, the FIRST included", async t => {
  // No exemption (2026-09-26 ruling). Exempting the first frame left the hole one level up:
  // an upgrade costs six units, so at the shipped 60 rpm a client could open ten sockets a
  // minute and carry ten free ~40-symbol seeds. So the first frame is charged like any other.
  const f = await gridFixture(t, { quoteDailyLimit: 5 });
  const { ws, up } = await gridRelayed(f, "MSFT,TSLA,NVDA");
  await within(up, "message");
  // Three symbols on the FIRST frame, three units of the SAME counter /api spends: two left.
  assert.equal((await http(f.port, quote)).status, 200);
  assert.equal((await http(f.port, quote)).status, 200);
  assert.equal((await http(f.port, quote)).status, 429);
  ws.terminate();
});

test("a grid frame the daily cap cannot pay for closes the relay, and hands the slot back", async t => {
  const f = await gridFixture(t, { quoteDailyLimit: 3 });
  const { ws, up } = await gridRelayed(f);          // one symbol on the first frame: one unit
  await within(up, "message");
  const second = within(up, "message");
  ws.send(JSON.stringify({ params: { symbol: "MSFT,TSLA" } }));   // two more: three of three
  await second;
  assert.equal((await http(f.port, quote)).status, 429, "the counter should be spent");
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  // Nothing left, so the next frame cannot be paid for at all and the relay closes rather
  // than forwarding a list the door has not paid for.
  ws.send(JSON.stringify({ params: { symbol: "AAPL" } }));
  await closed;
  await upClosed;
  await gridSlotReleased(f);
});

test("the upgrade's six units pay the per-minute budget for the FIRST frame, and nothing more", async t => {
  // The other half of the ruling, and the half a symbol-counting test cannot see: the six
  // units buy the door's slot and the PER-MINUTE budget for that first frame. With
  // requestsPerMinute at exactly six the upgrade spends the whole minute, so a first frame
  // that charged spend(1) as well would close the relay instead of seeding the grid.
  const f = await gridFixture(t, { requestsPerMinute: 6 });
  const { ws, up } = await gridRelayed(f);
  assert.equal((await within(up, "message"))[0].toString(),
    JSON.stringify({ params: { symbol: "AAPL" } }));
  // And a LATER frame does cost a per-minute unit, of which there is now none: it closes.
  // (No gridSlotReleased here -- a second upgrade would need six units this fixture has
  // deliberately spent. Three other tests prove the slot comes back.)
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  ws.send(JSON.stringify({ params: { symbol: "MSFT" } }));
  await closed;
  await upClosed;
});

test("a grid socket whose FIRST frame the daily cap cannot pay for never relays it", async t => {
  // The churn case directly: the counter is already spent, so an upgrade buys a slot and a
  // per-minute unit and nothing else -- the first frame is refused like any other.
  const f = await gridFixture(t, { quoteDailyLimit: 1 });
  assert.equal((await http(f.port, quote)).status, 200);          // the only unit, spent
  const { ws } = await gridConnect(f);
  const closed = within(ws, "close");
  ws.send(JSON.stringify({ params: { symbol: "AAPL,MSFT" } }));
  await closed;
  await gridSlotReleased(f);
});

test("a grid socket's frames are capped over its lifetime whatever the budgets allow", async t => {
  // The backstop on its own: budgets wide enough that neither is what refuses, single
  // symbols so the daily charge is one a frame, and 60 more frames after the first.
  const f = await gridFixture(t, { quoteDailyLimit: 10000, requestsPerMinute: 600 });
  const { ws, up } = await gridRelayed(f);
  await within(up, "message");
  const closed = within(ws, "close", 4000);
  const upClosed = within(up, "close", 4000);
  // 60 validated frames a socket, all charged: the first plus 59 more are accepted, the 61st
  // closes it. Single symbols, and both budgets wide enough that neither is what refuses.
  for (let i = 0; i < 60; i++) ws.send(JSON.stringify({ params: { symbol: "AAPL" } }));
  await closed;
  await upClosed;
  await gridSlotReleased(f);
});

// ---- The tick chart's socket: this line's own, and the only PUSH-ONLY one the door
// carries. live-grid reads no client frame from it -- the query is the subscription -- so
// everything about it differs from live_grid_ws except the bounds.

const TA_WS = "/grid/ta_chart_ws?symbol=NVDA&interval=1m";

/** A tick-chart fixture: the same cap of one, the same connection queue, and openGrid
 *  injected so the TARGET it is asked to dial can be asserted. */
async function taFixture(t, overrides = {}) {
  const grid = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(grid, "listening");
  const nextConnection = connectionQueue(grid);
  t.after(() => new Promise(resolve => {
    for (const ws of grid.clients) ws.terminate(); grid.close(resolve);
  }));
  const dialled = [];
  const gw = await fixture(t, { maxSockets: 1, ...overrides }, {
    openGrid: (_, path) => {
      dialled.push(path);
      return new WebSocket(`ws://127.0.0.1:${grid.address().port}`);
    },
  });
  return { ...gw, nextConnection, dialled };
}
/** The live-grid side of the tick chart's connection, BOUNDED. nextConnection() never
 *  rejects, so a regression that stops dialling at upgrade would hang the suite instead of
 *  failing it -- the same reason every teardown assertion here uses within(). */
function dialled(f, ms = 2000) {
  let timer;
  return Promise.race([
    f.nextConnection().finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`live-grid was never dialled within ${ms}ms`)), ms);
    }),
  ]);
}
/** The slot came back: with maxSockets at 1, a second tick-chart socket only opens if the
 *  first was released. */
async function taSlotReleased(f) {
  const again = await wsConnect(f.port, undefined, TA_WS);
  assert.equal(again.status, 101, "the socket slot was not released");
  again.ws.terminate();
}

test("the tick chart's socket dials live-grid at upgrade, with the validated query and no frame", async t => {
  const f = await taFixture(t);
  const { ws, status } = await wsConnect(f.port, undefined, TA_WS);
  assert.equal(status, 101);
  // Opened WITHOUT a client frame: live-grid's /ta_chart_ws reads ws.query_params and loops
  // on send_json, so there is nothing to wait for and the upstream is dialled here.
  const up = await dialled(f);
  // The target socketTarget validated, with the door's own /grid prefix stripped.
  assert.deepEqual(f.dialled, ["/ta_chart_ws?symbol=NVDA&interval=1m"]);
  // A push relays; the figure is forwarded unchanged.
  const pushed = within(ws, "message");
  up.send('{"type":"figure","rev":0}');
  assert.equal((await pushed)[0].toString(), '{"type":"figure","rev":0}');
  // And a frame from the CLIENT closes the relay: live-grid would ignore it, so a door that
  // swallowed it silently would be lying about the contract.
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  ws.send(JSON.stringify({ params: { symbol: "NVDA" } }));
  await closed;
  await upClosed;
  await taSlotReleased(f);
});

test("EVERY tick-chart push charges the daily counter, the FIRST included, and the cap closes the stream", async t => {
  const f = await taFixture(t, { quoteDailyLimit: 3 });
  const { ws } = await wsConnect(f.port, undefined, TA_WS);
  const up = await dialled(f);
  // The paid unit on THIS socket is the upstream push -- each one re-runs build_series
  // through openbb-api's historical route -- and there is NO exemption (2026-09-26 ruling):
  // the build_series the upgrade itself triggers is paid work like every later one, and
  // exempting it would let socket churn buy one free fetch per upgrade.
  for (const push of ['{"rev":0}', '{"rev":1}', '{"rev":2}']) {
    const seen = within(ws, "message");
    up.send(push);
    await seen;
  }
  // Three pushes, THREE units of the same counter /api spends: nothing left at all.
  assert.equal((await http(f.port, quote)).status, 429);
  // The next push cannot be paid for, so the stream closes rather than going quietly stale.
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  up.send('{"rev":3}');
  await closed;
  await upClosed;
  await taSlotReleased(f);
});

test("a tick-chart socket whose FIRST push the daily cap cannot pay for relays nothing", async t => {
  // The churn case on this leg: the counter is spent before the upgrade, so the socket opens,
  // live-grid is dialled, and its very first push is refused like any other.
  const f = await taFixture(t, { quoteDailyLimit: 1 });
  assert.equal((await http(f.port, quote)).status, 200);          // the only unit, spent
  const { ws } = await wsConnect(f.port, undefined, TA_WS);
  const up = await dialled(f);
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  up.send('{"rev":0}');
  await closed;
  await upClosed;
  await taSlotReleased(f);
});

test("the upgrade's six units pay the per-minute budget for the FIRST push, and nothing more", async t => {
  // The other half of the ruling on this leg. With requestsPerMinute at exactly six the
  // upgrade spends the whole minute, so a first push that ALSO charged spend(1) would close
  // the stream instead of relaying the figure. (No taSlotReleased -- a second upgrade would
  // need six units this fixture has deliberately spent.)
  const f = await taFixture(t, { requestsPerMinute: 6 });
  const { ws } = await wsConnect(f.port, undefined, TA_WS);
  const up = await dialled(f);
  const seen = within(ws, "message");
  up.send('{"type":"figure","rev":0}');
  assert.equal((await seen)[0].toString(), '{"type":"figure","rev":0}');
  // And a LATER push does cost a per-minute unit, of which there is now none: it closes.
  const closed = within(ws, "close");
  const upClosed = within(up, "close");
  up.send('{"rev":1}');
  await closed;
  await upClosed;
});

test("a tick chart's pushes are capped over its lifetime whatever the budgets allow", async t => {
  const f = await taFixture(t, { quoteDailyLimit: 10000, requestsPerMinute: 600 });
  const { ws } = await wsConnect(f.port, undefined, TA_WS);
  const up = await dialled(f);
  const closed = within(ws, "close", 4000);
  const upClosed = within(up, "close", 4000);
  // 60 pushes a socket, all charged: the first plus 59 more relay, the 61st closes it on the
  // cap alone. This is what bounds a stream -- no quoteDailyLimit lengthens it.
  for (let i = 0; i <= 60; i++) up.send(`{"rev":${i}}`);
  await closed;
  await upClosed;
  await taSlotReleased(f);
});

/**
 * The real dial, not the fake openGrid every relay test injects: connectGrid is what carries
 * the stack's credential onto live-grid's websocket handshake, and the brief's row-own names
 * "the Basic pair on every grid request AND socket". live-grid is plain HTTP on the bridge,
 * so unlike the wire's equivalent test this needs no certificate -- there is no TLS leg to
 * prove, which is the whole reason connectGrid dials ws:// rather than wss://.
 */
test("connectGrid dials live-grid bounded, uncompressed, credentialled and without following a redirect", async t => {
  const seen = [];
  const grid = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(grid, "listening");
  grid.on("connection", (_, req) => seen.push({ url: req.url, headers: req.headers }));
  t.after(() => new Promise(resolve => {
    for (const c of grid.clients) c.terminate(); grid.close(resolve);
  }));
  const cfg = { ...config(), gridOrigin: `http://127.0.0.1:${grid.address().port}` };
  const ws = connectGrid(cfg);
  await within(ws, "open");
  // live-grid's own route, and the "/grid" prefix the door strips never reaches the wire.
  assert.equal(seen[0].url, "/live_grid_ws");
  // The pair live-grid's BasicAuthMiddleware demands on the handshake as on every path, and
  // the Origin connectNews sends. Nothing of the caller's: the machine token never travels.
  assert.equal(seen[0].headers.authorization, cfg.apiAuthorization);
  assert.equal(seen[0].headers.origin, cfg.gridOrigin);
  assert.ok(!JSON.stringify(seen[0].headers).includes(TOKEN));
  // perMessageDeflate: false -- the handshake offers NO extension, so live-grid cannot
  // negotiate one (a compressed frame's expanded size is not what maxPayload measures).
  assert.equal(seen[0].headers["sec-websocket-extensions"], undefined);
  // maxPayload: an oversize frame from live-grid is refused by this client rather than
  // buffered. 65537 is one byte past MAX_SOCKET, the same number the relay tests use.
  const failed = within(ws, "error");
  grid.clients.values().next().value.send("x".repeat(65537));
  const [tooBig] = await failed;
  assert.match(tooBig.message, /[Mm]ax payload/);
  ws.terminate();
  // followRedirects: false -- a redirect on the handshake is an error, never a second dial
  // to wherever live-grid was told to point.
  const redirect = createServer((_, res) => {
    res.writeHead(302, { Location: "http://127.0.0.1:9/live_grid_ws" }); res.end();
  });
  redirect.listen(0, "127.0.0.1"); await once(redirect, "listening");
  t.after(() => new Promise(resolve => redirect.close(resolve)));
  const refused = connectGrid({ ...cfg, gridOrigin: `http://127.0.0.1:${redirect.address().port}` });
  const [moved] = await within(refused, "error");
  assert.match(moved.message, /302/);
  refused.terminate();
  // And the scheme follows the origin's: an https gridOrigin would be dialled wss://, which
  // is the branch a TLS-fronted live-grid would take. No such deployment exists at this tag.
  const secure = connectGrid({ ...cfg, gridOrigin: "https://openbb-live-grid.invalid:6903" });
  secure.on("error", () => {});
  assert.ok(secure.url.startsWith("wss://"), secure.url);
  secure.terminate();
});

// ---- openbq-docker v10: live-grid is the opt-in `live` compose profile, so the door must be
// told it runs ("liveGrid": true). Off -- the default when the key is absent -- every /grid
// route and socket that passes its route rules answers 503 and live-grid is never dialled; an
// unmatched /grid path is still the 404 it always was.

test("liveGrid off: gridOrigin is null, /grid answers 503 after the route rules, nothing is dialled", async t => {
  const { liveGrid, ...off } = settings;
  assert.equal(liveGrid, true, "the default fixture turns the live profile on");
  const cfg = validateConfig(off, secrets);
  assert.equal(cfg.gridOrigin, null);
  assert.equal(validateConfig({ ...off, liveGrid: false }, secrets).gridOrigin, null);
  let dialled = 0;
  const { port, calls } = await fixture(t, { gridOrigin: null }, {
    openGrid: () => { dialled++; throw new Error("live-grid must not be dialled"); },
  });
  for (const path of ["/grid/widgets.json", "/grid/apps.json", "/grid/live_grid?symbol=AAPL",
    "/grid/symbol_meta?symbol=AAPL", "/grid/series?symbol=AAPL", "/grid/chart?symbol=AAPL",
    "/grid/ticks?symbol=AAPL", "/grid/ta_chart?symbol=AAPL"]) {
    assert.equal((await http(port, path)).status, 503, path);
  }
  // The route rules still run first: an unmatched or out-of-grammar path is a 404, never a 503.
  for (const path of ["/grid/demo", "/grid/ticks?symbol=AAPL&limit=0", "/grid/ta_chart?symbol=AAPL&provider=eodhd"]) {
    assert.equal((await http(port, path)).status, 404, path);
  }
  assert.equal((await gridConnect({ port })).status, 503);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/grid/ta_chart_ws?symbol=AAPL")).status, 503);
  assert.equal((await wsConnect(port, { ...HEADERS, Origin: ORIGIN }, "/grid/ta_chart_ws")).status, 404);
  assert.equal(calls.length, 0);
  assert.equal(dialled, 0);
  // Off is not "free": a 503 never touched the daily vendor counter. With a cap of one,
  // the /api quote after eight refused grid calls still answers.
  const capped = await fixture(t, { gridOrigin: null, quoteDailyLimit: 1 });
  for (let i = 0; i < 3; i++) assert.equal((await http(capped.port, "/grid/live_grid?symbol=AAPL")).status, 503);
  assert.equal((await http(capped.port, quote)).status, 200);
});

test("liveGrid off: the preflight does not dial live-grid; on, it does", async t => {
  const api = createServer((req, res) => { res.writeHead(req.headers.authorization ? 422 : 401); res.end(); });
  api.listen(0, "127.0.0.1"); await once(api, "listening");
  t.after(() => new Promise(resolve => api.close(resolve)));
  const grid = await gridStub(t);
  grid.status = 500; // would fail the preflight if it were asked
  const base = { ...config(), rssOrigin: null, rssAddress: null, feeds: {},
    apiOrigin: `http://127.0.0.1:${api.address().port}` };
  await checkUpstreams({ ...base, gridOrigin: null });
  assert.deepEqual(grid.seen, []);
  await assert.rejects(checkUpstreams({ ...base, gridOrigin: grid.origin }), /live-grid preflight failed \(HTTP 500\)/);
  assert.deepEqual(grid.seen.map(r => r.path), ["/health"]);
});

test("the grid socket's own first-frame and lifetime deadlines are bounded, and it costs six", async t => {
  const first = await fixture(t, {}, { firstFrameMs: 30, openGrid: () => new WebSocket("ws://127.0.0.1:9") });
  const a = await gridConnect(first); await once(a.ws, "close");
  const second = await fixture(t, {}, { firstFrameMs: 1000, socketMs: 30, openGrid: () => new WebSocket("ws://127.0.0.1:9") });
  const b = await gridConnect(second); await once(b.ws, "close");
  // Charged before handleUpgrade, out of the same per-minute budget the REST side spends
  // from: with six units left one grid socket is admitted and /_gateway/health is then 429.
  const metered = await fixture(t, { requestsPerMinute: 6 }, { openGrid: () => new WebSocket("ws://127.0.0.1:9") });
  const only = await gridConnect(metered); assert.equal(only.status, 101);
  assert.equal((await http(metered.port, "/_gateway/health")).status, 429);
  assert.equal((await gridConnect(metered)).status, 429);
  only.ws.terminate();
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

// --- live-grid's Subscriptions page and watchlist API behind /grid (V10-P5, 2026-10-13) ---

function sendBody(port, path, { method = "POST", headers = HEADERS, body } = {}) {
  return new Promise((resolve, reject) => {
    const h = { ...headers };
    if (body !== undefined) { h["Content-Type"] ??= "application/json"; h["Content-Length"] = String(Buffer.byteLength(body)); }
    const req = request({ host: "127.0.0.1", port, path, method, headers: h }, res => {
      const parts = [];
      res.on("data", c => parts.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(parts).toString() }));
    });
    req.on("error", reject); req.end(body);
  });
}
async function subscriptionsFixture(t, overrides = {}, answer = () => ({ status: 200, json: { used: 1, cap: 50 } })) {
  const sent = [], fetched = [];
  const fx = await fixture(t, overrides, {
    sendSubscription: async (method, path, body) => { sent.push({ method, path, body }); return answer(method, path, body); },
    fetchPage: async () => { fetched.push(1); return "<!doctype html><p>subscriptions</p>"; },
  });
  return { ...fx, sent, fetched };
}

test("the Subscriptions page loads WITHOUT the token -- a frame cannot send one -- from memory, with its own CSP", async t => {
  const { port, fetched, calls } = await subscriptionsFixture(t);
  const anon = { Host: new URL(ORIGIN).host };
  for (let i = 0; i < 3; i++) {
    const r = await http(port, "/grid/subscriptions", anon);
    assert.equal(r.status, 200);
    assert.match(r.headers["content-type"], /^text\/html/);
    assert.equal(r.text, "<!doctype html><p>subscriptions</p>");
    assert.match(r.headers["content-security-policy"], /default-src 'none'/);
    assert.match(r.headers["content-security-policy"], /connect-src 'self'/);
    assert.doesNotMatch(r.headers["content-security-policy"], /frame-ancestors/);
    assert.equal(r.headers["cache-control"], "no-store");
  }
  // Fetched from live-grid once; nothing else was asked of any upstream.
  assert.equal(fetched.length, 1);
  assert.equal(calls.length, 0);
  // The token is accepted too, and it is the same page.
  assert.equal((await http(port, "/grid/subscriptions")).status, 200);
  assert.equal(fetched.length, 1);
});

test("the token exception is the page alone: exact path, GET, no query, this Host", async t => {
  const { port, fetched } = await subscriptionsFixture(t);
  const anon = { Host: new URL(ORIGIN).host };
  for (const path of ["/grid/subscriptions?x=1", "/grid/subscriptions/", "/grid/api/subscriptions",
    "/grid/widgets.json", "/grid/demo", "/grid/health", "/_gateway/health"]) {
    assert.equal((await http(port, path, anon)).status, 401, path);
  }
  assert.equal((await http(port, "/grid/subscriptions", anon, "POST")).status, 401);
  assert.equal((await http(port, "/grid/subscriptions", { Host: "evil.example" })).status, 421);
  assert.equal(fetched.length, 0);
  // With the token, a query on the page is still not a route.
  assert.equal((await http(port, "/grid/subscriptions?x=1")).status, 404);
});

test("the page answers 503 with live-grid off, and a failed fetch is retried, not cached", async t => {
  const off = await subscriptionsFixture(t, { gridOrigin: null });
  assert.equal((await http(off.port, "/grid/subscriptions", { Host: new URL(ORIGIN).host })).status, 503);
  assert.equal(off.fetched.length, 0);
  let fail = true; const tries = [];
  const flaky = await fixture(t, {}, { fetchPage: async () => {
    tries.push(1); if (fail) throw new Error("down"); return "<p>ok</p>";
  } });
  assert.equal((await http(flaky.port, "/grid/subscriptions", { Host: new URL(ORIGIN).host })).status, 502);
  fail = false;
  assert.equal((await http(flaky.port, "/grid/subscriptions", { Host: new URL(ORIGIN).host })).text, "<p>ok</p>");
  assert.equal(tries.length, 2);
});

test("the watchlist API is behind the lock, and live-grid's payload is relayed", async t => {
  const { port, sent } = await subscriptionsFixture(t);
  assert.equal((await http(port, "/grid/api/subscriptions", { Host: new URL(ORIGIN).host })).status, 401);
  assert.equal(sent.length, 0);
  const r = await http(port, "/grid/api/subscriptions");
  assert.equal(r.status, 200);
  assert.deepEqual(JSON.parse(r.text), { used: 1, cap: 50 });
  assert.deepEqual(sent, [{ method: "GET", path: "/api/subscriptions", body: undefined }]);
});

test("POST rebuilds the body from a validated symbol and charges one vendor unit", async t => {
  const { port, sent } = await subscriptionsFixture(t, { quoteDailyLimit: 1 },
    (method) => (method === "POST" ? { status: 201, json: { used: 2, cap: 50 } } : { status: 200, json: {} }));
  const r = await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol: " BTC-USD ", extra: "dropped" }) });
  assert.equal(r.status, 201);
  assert.deepEqual(JSON.parse(r.text), { used: 2, cap: 50 });
  assert.deepEqual(sent, [{ method: "POST", path: "/api/subscriptions", body: JSON.stringify({ symbol: "BTC-USD" }) }]);
  // The daily vendor cap of one is spent.
  assert.equal((await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol: "ETH-USD" }) })).status, 429);
  assert.equal(sent.length, 1);
});

test("POST refuses a bad symbol, a non-JSON body and an oversized one before any upstream call", async t => {
  const { port, sent } = await subscriptionsFixture(t);
  for (const symbol of ["", "A B", "x".repeat(25), "../x", 7, null]) {
    const r = await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol }) });
    assert.equal(r.status, 422, String(symbol));
    assert.equal(JSON.parse(r.text).detail, "Not a symbol.");
  }
  assert.equal((await sendBody(port, "/grid/api/subscriptions", { body: "{", })).status, 400);
  assert.equal((await sendBody(port, "/grid/api/subscriptions",
    { body: JSON.stringify({ symbol: "AAPL" }), headers: { ...HEADERS, "Content-Type": "text/plain" } })).status, 415);
  assert.equal((await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol: "A".repeat(2000) }) })).status, 413);
  assert.equal(sent.length, 0);
});

test("DELETE takes one symbol in the path; other methods and shapes are not routes", async t => {
  const { port, sent } = await subscriptionsFixture(t);
  assert.equal((await http(port, "/grid/api/subscriptions/BTC-USD", HEADERS, "DELETE")).status, 200);
  assert.equal((await http(port, "/grid/api/subscriptions/^GSPC", HEADERS, "DELETE")).status, 200);
  assert.deepEqual(sent.map(s => [s.method, s.path]),
    [["DELETE", "/api/subscriptions/BTC-USD"], ["DELETE", "/api/subscriptions/^GSPC"]]);
  for (const [path, method] of [["/grid/api/subscriptions", "DELETE"], ["/grid/api/subscriptions/BTC-USD", "GET"],
    ["/grid/api/subscriptions/BTC-USD", "POST"], ["/grid/api/subscriptions/A/B", "DELETE"],
    ["/grid/api/subscriptions?symbol=X", "GET"], ["/grid/api/subscriptions", "PUT"],
    ["/grid/api/subscriptions/" + "A".repeat(25), "DELETE"]]) {
    assert.equal((await http(port, path, HEADERS, method)).status, 404, `${method} ${path}`);
  }
  assert.equal(sent.length, 2);
});

test("live-grid's refusals become the door's own messages; anything else is a 502", async t => {
  let status = 409;
  const { port } = await subscriptionsFixture(t, {}, () => ({ status }));
  for (const [code, text] of [[409, "already subscribed"], [507, "cap is reached"], [404, "not on the watchlist"]]) {
    status = code;
    const r = await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol: "AAPL" }) });
    assert.equal(r.status, code);
    assert.match(JSON.parse(r.text).detail, new RegExp(text));
  }
  status = 500;
  assert.equal((await http(port, "/grid/api/subscriptions")).status, 502);
});

test("a foreign Origin and live-grid off both refuse the watchlist API", async t => {
  const { port, sent } = await subscriptionsFixture(t);
  assert.equal((await sendBody(port, "/grid/api/subscriptions",
    { body: JSON.stringify({ symbol: "AAPL" }), headers: { ...HEADERS, Origin: "https://evil.example" } })).status, 403);
  // The page's own fetches carry this door's origin and pass.
  assert.equal((await sendBody(port, "/grid/api/subscriptions",
    { body: JSON.stringify({ symbol: "AAPL" }), headers: { ...HEADERS, Origin: ORIGIN } })).status, 200);
  assert.equal(sent.length, 1);
  const off = await subscriptionsFixture(t, { gridOrigin: null });
  assert.equal((await http(off.port, "/grid/api/subscriptions")).status, 503);
});

test("/grid/widgets.json points the Subscriptions frame at this door; nothing else is rewritten", async t => {
  const spec = {
    subscriptions: { type: "iframe", endpoint: "http://live-grid:6903/subscriptions" },
    live_grid: { type: "live_grid", endpoint: "live_grid" },
  };
  const { port } = await fixture(t, {}, { requestJson: async () => structuredClone(spec) });
  const body = JSON.parse((await http(port, "/grid/widgets.json")).text);
  assert.equal(body.subscriptions.endpoint, `${ORIGIN}/grid/subscriptions`);
  assert.deepEqual(body.live_grid, spec.live_grid);
  // No subscriptions widget, or one that is not a frame: untouched.
  assert.deepEqual(rewriteGridWidgets({ a: { type: "table" } }, config()), { a: { type: "table" } });
  assert.deepEqual(rewriteGridWidgets({ subscriptions: { type: "table", endpoint: "x" } }, config()),
    { subscriptions: { type: "table", endpoint: "x" } });
  // The /api manifest is never rewritten.
  const api = await fixture(t, {}, { requestJson: async () => structuredClone(spec) });
  assert.deepEqual(JSON.parse((await http(api.port, "/api/widgets.json")).text), spec);
});

test("subscriptionRoute: the whole grammar", () => {
  const u = p => new URL(p, ORIGIN);
  assert.deepEqual(subscriptionRoute(u("/grid/api/subscriptions"), "GET"), { method: "GET", path: "/api/subscriptions" });
  assert.deepEqual(subscriptionRoute(u("/grid/api/subscriptions"), "POST"), { method: "POST", path: "/api/subscriptions" });
  assert.deepEqual(subscriptionRoute(u("/grid/api/subscriptions/EURUSD"), "DELETE"),
    { method: "DELETE", path: "/api/subscriptions/EURUSD" });
  assert.equal(subscriptionRoute(u("/grid/api/subscriptions/a.b_c-d"), "DELETE").path, "/api/subscriptions/a.b_c-d");
  for (const [p, m] of [["/grid/api/subscriptions?x=1", "GET"], ["/grid/api/subscriptions", "DELETE"],
    ["/grid/api/subscriptions/x", "PUT"], ["/grid/api/subscriptionsX", "GET"]]) {
    assert.equal(subscriptionRoute(u(p), m), null, `${m} ${p}`);
  }
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

// v10 walk: the desktop's packaged Origin (V10-P1) reaches the managed table routes as the desktop principal,
// behind the Bearer lock; any other foreign Origin is still refused before anything is relayed.
test("table routes admit the packaged desktop Origins behind the lock, and no other", async t => {
  const {call,calls}=await tableFixture(t);
  for (const origin of ["tauri://localhost","http://tauri.localhost"]) {
    assert.equal((await call("/table/sessions","POST",'{}',{Origin:origin})).status,200);
    assert.equal(calls.at(-1).headers["x-table-principal"],"desktop:owner");
  }
  for (const origin of ["http://localhost:1420","https://evil.example"]) assert.equal((await call("/table/sessions","POST",'{}',{Origin:origin})).status,403);
  assert.equal((await call("/table/sessions","POST",'{}',{Origin:"tauri://localhost",Authorization:""})).status,401);
  assert.equal(calls.length,2);
});

// ---- The reference's socket (openbq-docker v3.0.0, here beside the wire): /ref/live_grid_ws, ref_relayed to the
// keyless reference. The machine path (token + the gateway's own Origin) and the browser's
// ticket path (previewOrigin + a single-use ticket over the exact target).
const LIVE = "/ref/live_grid_ws";
const refused = () => new WebSocket("ws://127.0.0.1:9"); // nothing listens: the connect fails
function refConnect(port, headers = { ...HEADERS, Origin: ORIGIN }, path = LIVE) {
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
const SUB = '{"params":{"symbol":"AAPL"}}';

test("/ref/live_grid_ws: the upgrade gate wants the token, the gateway's Origin, the exact path and no subprotocol", async t => {
  let opened = 0;
  const { port, calls } = await fixture(t, {}, { openRef: () => { opened++; return refused(); } });
  assert.equal((await refConnect(port, { Host: HEADERS.Host, Origin: ORIGIN })).status, 401);
  assert.equal((await refConnect(port, { ...HEADERS, Authorization: "Bearer wrong", Origin: ORIGIN })).status, 401);
  assert.equal((await refConnect(port, HEADERS)).status, 403);
  assert.equal((await refConnect(port, { ...HEADERS, Origin: "https://untrusted.invalid" })).status, 403);
  assert.equal((await refConnect(port, { ...HEADERS, Host: "wrong.invalid", Origin: ORIGIN })).status, 403);
  // The desktop webview's own socket (its ticket, /grid/ws_ticket) arrives at v10.
  for (const origin of DESKTOP) assert.equal((await refConnect(port, { ...HEADERS, Origin: origin })).status, 403, origin);
  for (const path of [LIVE + "?symbol=AAPL", LIVE + "/", "/ref/widgets.json", "/ref/other_ws",
    "/grid/ta_series_ws", "/state/42", "/table/healthz", "/nope"]) { // /news/ws/news is the wire's socket here
    assert.equal((await refConnect(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
  }
  assert.equal((await refConnect(port, { ...HEADERS, Origin: ORIGIN, "Sec-WebSocket-Protocol": "chat" })).status, 404);
  // A non-GET upgrade on the right path, with the token and Origin, is still 404.
  const post = await new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path: LIVE, method: "POST", headers: { ...HEADERS, Origin: ORIGIN,
      Connection: "Upgrade", Upgrade: "websocket", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==" } },
      res => { res.resume(); resolve(res.statusCode); });
    req.once("upgrade", () => reject(new Error("upgraded")));
    req.once("error", reject); req.end();
  });
  assert.equal(post, 404);
  assert.equal(opened, 0); assert.equal(calls.length, 0);
});


test("/ref/live_grid_ws: a browser socket is admitted on a ticket: right target, right Origin, once", async t => {
  const { port } = await fixture(t, { previewOrigin: PREVIEW }, { openRef: refused });
  const ticket = socketTicket(TOKEN, LIVE);
  const admitted = await refConnect(port, browser, ticketed(LIVE, ticket));
  assert.equal(admitted.status, 101); admitted.ws.terminate();
  // Single use: the same ticket, replayed inside its thirty seconds, is refused.
  assert.equal((await refConnect(port, browser, ticketed(LIVE, ticket))).status, 401);
  // Wrong Origin (the gateway's own included), wrong key, wrong target, expired, junk, doubled.
  assert.equal((await refConnect(port, { ...browser, Origin: "https://evil.example.com" }, ticketed(LIVE, socketTicket(TOKEN, LIVE)))).status, 403);
  assert.equal((await refConnect(port, { ...browser, Origin: ORIGIN }, ticketed(LIVE, socketTicket(TOKEN, LIVE)))).status, 403);
  assert.equal((await refConnect(port, { Origin: PREVIEW }, ticketed(LIVE, socketTicket(TOKEN, LIVE)))).status, 401); // Host
  assert.equal((await refConnect(port, browser, ticketed(LIVE, socketTicket(TOKEN + "x", LIVE)))).status, 401);
  // A ticket names its target: one signed for another path does not open this one ...
  assert.equal((await refConnect(port, browser, ticketed(LIVE, socketTicket(TOKEN, "/grid/live_grid_ws")))).status, 401);
  // ... and a valid ticket over a path that is not a socket route opens nothing.
  assert.equal((await refConnect(port, browser, ticketed("/grid/ta_series_ws", socketTicket(TOKEN, "/grid/ta_series_ws")))).status, 404);
  assert.equal((await refConnect(port, browser, ticketed(LIVE + "?x=1", socketTicket(TOKEN, LIVE + "?x=1")))).status, 404);
  assert.equal((await refConnect(port, browser, ticketed(LIVE, socketTicket(TOKEN, LIVE, Date.now() - 31_000)))).status, 401);
  assert.equal((await refConnect(port, browser, ticketed(LIVE, "junk"))).status, 401);
  const two = socketTicket(TOKEN, LIVE);
  assert.equal((await refConnect(port, browser, `${LIVE}?ticket=${two}&ticket=${two}`)).status, 401);
  // A key the URL parser decodes to "ticket" but the wire never spells is not a ticket.
  assert.equal((await refConnect(port, browser, `${LIVE}?tick%65t=${socketTicket(TOKEN, LIVE)}`)).status, 401);
  assert.equal((await refConnect(port, { ...browser, "Sec-WebSocket-Protocol": "chat" }, ticketed(LIVE, socketTicket(TOKEN, LIVE)))).status, 404);
  // No ticket and no bearer is what it always was; a ticket buys nothing on the REST side.
  assert.equal((await refConnect(port, browser, LIVE)).status, 401);
  assert.equal((await http(port, ticketed(quote, socketTicket(TOKEN, quote)), browser)).status, 401);
});

test("/ref/live_grid_ws: a ticket replayed at its exact expiry millisecond is still refused", async t => {
  let clock = 1_700_000_000_000;
  const { port } = await fixture(t, { previewOrigin: PREVIEW }, { openRef: refused, now: () => clock });
  const ticket = socketTicket(TOKEN, LIVE, clock);
  const admitted = await refConnect(port, browser, ticketed(LIVE, ticket));
  assert.equal(admitted.status, 101); admitted.ws.terminate();
  clock += 30_000; // now === expiry: the verifier still accepts it, so the nonce must still be held
  assert.equal((await refConnect(port, browser, ticketed(LIVE, ticket))).status, 401);
});

test("/ref/live_grid_ws: tickets are off until the operator names the preview origin", async t => {
  const { port } = await fixture(t, {}, { openRef: refused });
  assert.equal((await refConnect(port, browser, ticketed(LIVE, socketTicket(TOKEN, LIVE)))).status, 401);
  // ... and the machine path is untouched by any of this.
  const machine = await refConnect(port); assert.equal(machine.status, 101); machine.ws.terminate();
});

// A loopback stand-in for the reference's socket: records each connection's request and frames.
async function reference(t) {
  const server = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(server, "listening");
  t.after(() => new Promise(resolve => { for (const ws of server.clients) ws.terminate(); server.close(resolve); }));
  const ready = [], waiting = [];
  server.on("connection", (ws, req) => {
    ws.frames = []; ws.request = req;
    ws.on("message", data => ws.frames.push(data.toString()));
    const next = waiting.shift(); next ? next(ws) : ready.push(ws);
  });
  const next = () => (ready.length ? Promise.resolve(ready.shift()) : new Promise(resolve => waiting.push(resolve)));
  return { server, next, origin: `http://127.0.0.1:${server.address().port}` };
}
// The slot is back: with maxSockets at 1, a second socket only opens if the first was released.
async function refSlotReleased(port) {
  const again = await refConnect(port);
  assert.equal(again.status, 101, "the socket slot was not released");
  again.ws.terminate();
}
async function ref_relayed(t, overrides = {}, dependencies = {}) {
  const ref = await reference(t);
  // The real connectRef, pointed at the loopback stand-in: what is proved is its URL and headers.
  const gw = await fixture(t, { maxSockets: 1, refOrigin: ref.origin, ...overrides }, dependencies);
  const { ws } = await refConnect(gw.port);
  ws.send(SUB);
  const up = await ref.next();
  while (!up.frames.length) await new Promise(resolve => setTimeout(resolve, 5));
  return { ...gw, ref, ws, up };
}

test("/ref/live_grid_ws: the reference socket is keyless, relays the rebuilt frame, re-validates every frame", async t => {
  const { ws, up, ref } = await ref_relayed(t);
  // connectRef: the fixed path on the reference's origin, no credential, no subprotocol.
  assert.equal(up.request.url, "/live_grid_ws");
  assert.equal(up.request.headers.authorization, undefined);
  assert.equal(up.request.headers.cookie, undefined);
  assert.equal(up.request.headers["sec-websocket-protocol"], undefined);
  assert.deepEqual(up.frames, [SUB]);
  const pushed = once(ws, "message");
  up.send('{"type":"tick","symbol":"AAPL"}');
  assert.equal((await pushed)[0].toString(), '{"type":"tick","symbol":"AAPL"}');
  // A symbol change over the same socket: re-validated, forwarded on the SAME upstream.
  ws.send('{ "params": { "symbol": "AAPL,MSFT" } }');
  while (up.frames.length < 2) await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(up.frames, [SUB, '{"params":{"symbol":"AAPL,MSFT"}}']);
  assert.equal(ref.server.clients.size, 1);
  // An invalid later frame closes both ends; nothing of it is forwarded.
  const closed = within(ws, "close"), upClosed = within(up, "close");
  ws.send('{"params":{"symbol":"AAPL"},"admin":1}');
  await closed; await upClosed;
  assert.equal(up.frames.length, 2);
});

test("/ref/live_grid_ws: bad, binary or oversized frames never open the reference socket", async t => {
  let opened = 0;
  const { port } = await fixture(t, {}, { openRef: () => { opened++; throw new Error("Must not connect"); } });
  for (const frame of ["not-json", '{"subscribe":[]}', '{"params":{"symbol":"AAPL","x":1}}', '{"params":{"ticker":"AAPL"}}',
    '{"params":{"symbol":"AAPL"},"admin":true}', '{"params":{"symbol":"A B"}}', Buffer.from(SUB), "x".repeat(65537)]) {
    const { ws } = await refConnect(port); const closed = within(ws, "close");
    ws.send(frame); await closed;
  }
  assert.equal(opened, 0);
});

test("/ref/live_grid_ws: an upstream that cannot be reached closes the client, and hands the slot back", async t => {
  const { port } = await fixture(t, { maxSockets: 1 }, { openRef: refused });
  const { ws } = await refConnect(port);
  const closed = within(ws, "close");
  ws.send(SUB);
  await closed;
  await refSlotReleased(port);
  // openRef throwing (a bad URL, say) is the same: closed, slot back.
  const thrown = await fixture(t, { maxSockets: 1 }, { openRef: () => { throw new Error("boom"); } });
  const second = await refConnect(thrown.port); const shut = within(second.ws, "close");
  second.ws.send(SUB); await shut;
  await refSlotReleased(thrown.port);
});

test("/ref/live_grid_ws: a client outrunning the reference (upstream back-pressure) closes the relay", async t => {
  // A stand-in upstream, already open, whose send buffer can be filled on demand.
  const up = Object.assign(new EventEmitter(), { readyState: WebSocket.OPEN, bufferedAmount: 0, sent: [],
    send(frame) { this.sent.push(frame); }, terminate() { this.terminated = true; } });
  const { port } = await fixture(t, { maxSockets: 1 }, { openRef: () => up });
  const { ws } = await refConnect(port);
  ws.send(SUB);
  while (!up.sent.length) await new Promise(resolve => setTimeout(resolve, 5));
  up.bufferedAmount = 262145;
  const closed = within(ws, "close");
  ws.send(SUB);
  await closed;
  assert.equal(up.sent.length, 1); assert.equal(up.terminated, true);
  await refSlotReleased(port);
});

test("/ref/live_grid_ws: the reference closing tears down the client, and hands the slot back", async t => {
  const { ws, up, port } = await ref_relayed(t);
  const closed = within(ws, "close");
  up.close();
  await closed;
  await refSlotReleased(port);
});

test("/ref/live_grid_ws: the client going away terminates the upstream connection, and hands the slot back", async t => {
  const { ws, up, port } = await ref_relayed(t);
  const upClosed = within(up, "close");
  ws.terminate();
  await upClosed;
  await refSlotReleased(port);
});

test("/ref/live_grid_ws: an oversized or binary frame from the reference closes the relay, and hands the slot back", async t => {
  for (const [what, send] of [
    ["oversized", up => up.send("x".repeat(65537))],
    ["binary", up => up.send(Buffer.from("tick"), { binary: true })],
  ]) {
    const { ws, up, port } = await ref_relayed(t);
    const closed = within(ws, "close");
    send(up);
    await closed.catch(error => { throw new Error(`${what}: ${error.message}`); });
    await refSlotReleased(port);
  }
});

test("/ref/live_grid_ws: a client too far behind is closed rather than queued behind, and hands the slot back", async t => {
  const { ws, up, port } = await ref_relayed(t);
  // The relay reads the server-side socket's bufferedAmount, which is deliberately not
  // exposed: the getter is stubbed for this one push, and restored before the follow-up.
  const real = Object.getOwnPropertyDescriptor(WebSocket.prototype, "bufferedAmount");
  const restore = () => Object.defineProperty(WebSocket.prototype, "bufferedAmount", real);
  t.after(restore);
  Object.defineProperty(WebSocket.prototype, "bufferedAmount", { configurable: true, get: () => 262145 });
  const closed = within(ws, "close");
  up.send('{"type":"tick"}');
  await closed;
  restore();
  await refSlotReleased(port);
});

test("/ref/live_grid_ws: a silent client is dropped at the first-frame deadline, and every socket at its lifetime", async t => {
  const first = await fixture(t, { maxSockets: 1 }, { firstFrameMs: 30, openRef: refused });
  const a = await refConnect(first.port); await within(a.ws, "close");
  await refSlotReleased(first.port);
  // The lifetime holds even for a socket that is subscribed and relaying.
  const { ws, up, port } = await ref_relayed(t, {}, { firstFrameMs: 1000, socketMs: 150 });
  const closed = within(ws, "close"), upClosed = within(up, "close");
  await closed; await upClosed;
  await refSlotReleased(port);
});

test("/ref/live_grid_ws: the socket cap and the six-unit socket price come from settings, charged before the upgrade", async t => {
  const capped = await fixture(t, { maxSockets: 1 }, { openRef: refused });
  const first = await refConnect(capped.port); assert.equal(first.status, 101);
  assert.equal((await refConnect(capped.port)).status, 429);
  first.ws.terminate();
  // Six left: exactly one socket is admitted, and the REST side is out of budget too.
  const metered = await fixture(t, { requestsPerMinute: 6 }, { openRef: refused });
  const only = await refConnect(metered.port); assert.equal(only.status, 101);
  assert.equal((await http(metered.port, "/_gateway/health")).status, 429);
  assert.equal((await refConnect(metered.port)).status, 429);
  only.ws.terminate();
});

test("/ref/live_grid_ws: a refused upgrade never allocates a socket slot, so the cap is not consumed by 404s", async t => {
  const { port } = await fixture(t, { maxSockets: 1 }, { openRef: refused });
  for (const path of [LIVE + "?x=1", "/grid/ta_series_ws", "/nope"]) {
    assert.equal((await refConnect(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
  }
  const admitted = await refConnect(port); assert.equal(admitted.status, 101); admitted.ws.terminate();
});
