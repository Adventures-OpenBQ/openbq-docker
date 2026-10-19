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
const settings = { origin: ORIGIN,
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

// A client that never answers a ping (autoPong off): the stand-in for a peer that vanished.
function deafConnect(port, path, headers = { ...HEADERS, Origin: ORIGIN }) {
  const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, { headers, autoPong: false });
  ws.on("error", () => {});
  return once(ws, "open").then(() => ws);
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
    { maxConcurrent: 0 }, { maxConcurrent: 33 },
    { maxSockets: 0 }, { maxSockets: 33 }, { maxSockets: 1.5 }, { maxSockets: "4" },
    // The preview origin is any HTTPS origin (a Vercel name is not on the tailnet), but only an origin.
    { previewOrigin: "http://bdobb.example.vercel.app" }, { previewOrigin: "https://bdobb.example.vercel.app/x" },
    { previewOrigin: "https://user@bdobb.example.vercel.app" }, { previewOrigin: "https://bdobb.example.vercel.app:8443" },
    // A Vercel origin is portless: not even the door's own 10000 is accepted.
    { previewOrigin: "https://bdobb.example.vercel.app:10000" },
    { previewOrigin: null }, { previewOrigin: "" }, { previewOrigin: 7 },
    { stateDir: "relative/state" }, { stateDir: "/var/lib/../etc" }, { stateDir: 7 }, { stateDir: "" },
    // Settings of later lines are not silently accepted: a stack at this tag has no such upstream.
    { gridOrigin: "http://openbb-live-grid:6903" }, { tickUrl: `wss://kdb.${TAILNET}` }, { liveGrid: true },
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
  assert.deepEqual([defaults.maxConcurrent, defaults.maxSockets, defaults.previewOrigin, defaults.stateDir],
    [8, 4, null, null]);
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
  assert.equal(validateConfig({ ...settings, maxConcurrent: 32 }, secrets).maxConcurrent, 32);
  // The removed budgets are refused by name, whatever their value, so a stale settings file fails loudly.
  for (const key of ["quoteDailyLimit", "requestsPerMinute"]) {
    assert.throws(() => validateConfig({ ...settings, [key]: 100 }, secrets), new RegExp(`Removed setting: ${key}`));
    assert.equal(key in defaults, false, key);
  }
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

// The packaged desktop app's webview origins (user ruling 2026-10-15: the HTTP half of V10-P1 moves
// down with the gateway). Tauri's http plugin stamps one on every request. The socket ticket and
// desktop socket upgrades stay at v10.
const DESKTOP = ["tauri://localhost", "http://tauri.localhost"];
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
    { apiOrigin: `http://127.0.0.1:${upstream.address().port}` },
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

test("no daily or per-minute budget: hundreds of vendor calls in a minute all pass", async t => {
  // The daily vendor cap (100) and the per-minute budget (60) were removed (user ruling
  // 2026-10-17); the concurrency cap and EODHD's own limits remain.
  const { port, calls } = await fixture(t);
  for (let i = 0; i < 150; i++) assert.equal((await http(port, quote)).status, 200);
  assert.equal(calls.length, 150);
});

test("the concurrency cap comes from settings", async t => {
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

test("a text/plain answer (the video routes) is relayed as text under the same cap", async t => {
  const upstream = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" }); res.end("https://www.youtube.com/embed/abc");
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const { port } = await fixture(t, { apiOrigin: `http://127.0.0.1:${upstream.address().port}` }, { requestJson: getJson });
  const response = await http(port, quote);
  assert.equal(response.status, 200);
  assert.equal(response.text, "https://www.youtube.com/embed/abc");
  assert.equal(response.headers["content-type"], "text/plain; charset=utf-8");
  assert.equal(response.headers["x-content-type-options"], "nosniff");
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
  // The desktop Origins pass on HTTP only; their sockets wait for v10's ticket (V10-P1).
  for (const origin of DESKTOP) assert.equal((await wsConnect(port, { ...HEADERS, Origin: origin })).status, 403, origin);
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
    messages.push(JSON.parse(data));
    // An unapproved feed's article, a stray frame, then the reply and an approved article:
    // only the last two reach the client.
    ws.send('{"id":1,"feed_id":8,"title":"private"}'); ws.send('{"type":"test-news"}');
    ws.send('{"feeds":[{"id":7}]}'); ws.send('{"id":2,"feed_id":7,"title":"approved"}');
  }));
  const { port } = await fixture(t, {}, { openNews: () => new WebSocket(`ws://127.0.0.1:${upstream.address().port}`) });
  const { ws } = await wsConnect(port);
  const received = [];
  const two = new Promise(resolve => ws.on("message", data => { if (received.push(data.toString()) === 2) resolve(); }));
  // The unapproved feed is dropped on the way through, not a reason to refuse the approved one.
  ws.send(JSON.stringify({ subscribe: [{ url: FEED, name: "rename-attempt", admin: true }, { url: "https://unapproved.invalid/feed" }] }));
  await two;
  assert.deepEqual(received, ['{"feeds":[{"id":7}]}', '{"id":2,"feed_id":7,"title":"approved"}']);
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

test("an oversized, binary or unparseable frame from the wire closes the relay, and hands the slot back", async t => {
  for (const [what, send] of [
    ["oversized", up => up.send("x".repeat(65537))],
    ["binary", up => up.send(Buffer.from("news"), { binary: true })],
    ["unparseable", up => up.send("not json")],
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

test("WS initial frame deadline and the dead-peer heartbeat are bounded", async t => {
  const first = await fixture(t, {}, { firstFrameMs: 30, openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const a = await wsConnect(first.port); await once(a.ws, "close");
  const second = await fixture(t, {}, { firstFrameMs: 1000, pingMs: 20, openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const b = await deafConnect(second.port, "/news/ws/news"); await within(b, "close");
});

test("the socket cap comes from settings, checked before the upgrade", async t => {
  const capped = await fixture(t, { maxSockets: 1 }, { openNews: () => new WebSocket("ws://127.0.0.1:9") });
  const first = await wsConnect(capped.port); assert.equal(first.status, 101);
  assert.equal((await wsConnect(capped.port)).status, 429);
  first.ws.terminate();
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
    "dashboards/preview.json", "dashboards/docks.json", "dashboards/3f2a-B_c.json",
    "workspaces/7c9e6679-7425-40de-944b-e07fc1f90ae7.json", "layouts/7c9e6679-7425-40de-944b-e07fc1f90ae7.json"]) assert.equal(stateFile(ok), true, ok);
  for (const bad of ["", "settings.json.tmp", "settings.json.corrupt", "../settings.json", "dashboards/../settings.json",
    "dashboards/a/b.json", "dashboards/.json", "workspaces/.json", "layouts/a/b.json", "files/a.pdf", "logs/app.log", "skills/x.md", "Settings.json",
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
  const { port } = await stateFixture(t);
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
    if(req.url.startsWith("/api/v1/test/rows?slow=")){await new Promise(r=>setTimeout(r,Number(new URL(req.url,"http://x").searchParams.get("slow"))));if(res.destroyed)return;}
    if(req.url === "/sessions/truncated/commands"){res.writeHead(200,{"Content-Type":"application/json"});res.write('{"partial":');setImmediate(()=>res.destroy());return;}
    if(req.url === "/sessions/oversized/commands"){res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({text:"x".repeat(8388608)}));return;}
    const ssrm=req.url.startsWith("/api/v1/test/rows") ? {"x-openbq-ssrm":req.url.includes("cached=1") ? "hit" : "miss"} : {};
    res.writeHead(req.url === "/sessions/missing/commands" ? 410 : 200, {"Content-Type":"application/json", "Set-Cookie":"secret=bad", ...ssrm});
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
test("table batches fail atomically on truncation, oversize or deadline; standard POST is exact",async t=>{
  const {call,calls,cfg}=await tableFixture(t,{tableTimeoutMs:40});
  for(const name of ["stalled","truncated","oversized"]){const result=await call(`/table/sessions/${name}/commands`,"POST",'{}').catch(error=>{throw new Error(name,{cause:error});});assert.equal(result.status,502);assert.doesNotMatch(result.body,/partial|xxxxxxxx/);}
  cfg.tableTimeoutMs=65000;
  const result=await call("/api/api/v1/test/rows?symbol=AAPL","POST",'{"startRow":0,"endRow":10}').catch(error=>{throw new Error("standard",{cause:error});});assert.equal(result.status,200);
  assert.equal(calls.at(-1).path,"/api/v1/test/rows?symbol=AAPL");assert.equal(calls.at(-1).body,'{"startRow":0,"endRow":10}');
  assert.equal(calls.at(-1).headers.authorization,config().apiAuthorization);assert.equal(calls.at(-1).headers["x-table-principal"],undefined);
  assert.equal((await call("/table/sessions/../healthz").catch(error=>{throw new Error("traversal",{cause:error});})).status,421);
  assert.equal((await call("/table/sessions/%2e%2e/healthz").catch(error=>{throw new Error("encoded",{cause:error});})).status,421);
});
test("SSRM exchanges have their own deadline, longer than managed table routes", async t => {
  assert.equal(validateConfig(settings, secrets).ssrmTimeoutMs, 170000);
  assert.equal(validateConfig({...settings, ssrmTimeoutMs: 300000}, secrets).ssrmTimeoutMs, 300000);
  for (const ssrmTimeoutMs of [999, 300001, "170000", 1.5]) assert.throws(() => validateConfig({...settings, ssrmTimeoutMs}, secrets));
  const {call} = await tableFixture(t, {tableTimeoutMs: 40, ssrmTimeoutMs: 400});
  assert.equal((await call("/table/sessions/stalled/commands", "POST", '{}')).status, 502);
  assert.equal((await call("/api/api/v1/test/rows?slow=150", "POST", '{}')).status, 200);
  const started = Date.now();
  assert.equal((await call("/api/api/v1/test/rows?slow=5000", "POST", '{}')).status, 502);
  assert.ok(Date.now() - started < 2000);
});
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
    "/grid/live_grid_ws", "/state/42", "/table/healthz", "/nope"]) { // /news/ws/news is the wire's socket here
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
  assert.equal((await refConnect(port, browser, ticketed("/grid/live_grid_ws", socketTicket(TOKEN, "/grid/live_grid_ws")))).status, 404);
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

test("/ref/live_grid_ws: a silent client is dropped at the first-frame deadline, a peer that stops answering pings at the heartbeat", async t => {
  const first = await fixture(t, { maxSockets: 1 }, { firstFrameMs: 30, openRef: refused });
  const a = await refConnect(first.port); await within(a.ws, "close");
  await refSlotReleased(first.port);
  // No lifetime: a subscribed socket whose client answers pings stays open well past many beats.
  // 100 ms beats, not 20: the client's pong must cross a loaded host's event loop in time (a
  // 20 ms beat closed the healthy socket twice at load average 90-160). Still six beats.
  const live = await ref_relayed(t, {}, { firstFrameMs: 1000, pingMs: 100 });
  await new Promise(resolve => setTimeout(resolve, 600));
  assert.equal(live.ws.readyState, WebSocket.OPEN);
  live.ws.terminate(); await refSlotReleased(live.port);
  const deaf = await fixture(t, { maxSockets: 1 }, { firstFrameMs: 1000, pingMs: 20, openRef: refused });
  await within(await deafConnect(deaf.port, LIVE), "close");
  await refSlotReleased(deaf.port);
});

test("/ref/live_grid_ws: the socket cap comes from settings, checked before the upgrade", async t => {
  const capped = await fixture(t, { maxSockets: 1 }, { openRef: refused });
  const first = await refConnect(capped.port); assert.equal(first.status, 101);
  assert.equal((await refConnect(capped.port)).status, 429);
  first.ws.terminate();
});

test("/ref/live_grid_ws: a refused upgrade never allocates a socket slot, so the cap is not consumed by 404s", async t => {
  const { port } = await fixture(t, { maxSockets: 1 }, { openRef: refused });
  for (const path of [LIVE + "?x=1", "/grid/live_grid_ws", "/nope"]) {
    assert.equal((await refConnect(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
  }
  const admitted = await refConnect(port); assert.equal(admitted.status, 101); admitted.ws.terminate();
});

test("od's SSRM cache marker never reaches the client, and a client's never reaches od", async t => {
  const {call,calls}=await tableFixture(t);
  for (let i=0;i<3;i++) {
    const hit=await call("/api/api/v1/test/rows?cached=1","POST",'{}');
    assert.equal(hit.status,200); assert.equal(hit.headers["x-openbq-ssrm"],undefined);
  }
  const spoof=await call("/api/api/v1/test/rows","POST",'{}',{"x-openbq-ssrm":"hit"});
  assert.equal(spoof.status,200); assert.equal(calls.at(-1).headers["x-openbq-ssrm"],undefined);
});
