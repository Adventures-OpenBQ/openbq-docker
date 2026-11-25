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
import { gunzipSync } from "node:zlib";
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
const settings = { origin: ORIGIN,
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
      res.on("end", () => {
        const body = Buffer.concat(parts);
        resolve({ status: res.statusCode, headers: res.headers, body, text: body.toString() });
      });
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



// The documented first deployment is `cp funnel-gateway/settings.example.json
// gateway-config/settings.json` then edit `origin` -- so the shipped example must actually
// validate, not merely look plausible. It ships with the wire off.






// The packaged desktop app's webview origins on /api (user ruling 2026-10-15: the HTTP half of V10-P1
// moved down to v4 with the gateway). DESKTOP is declared with the V10-P1 tests below.






















test("root manifests are gzipped for a caller that accepts gzip; data routes and other callers are not", async t => {
  // openbq-api's 5.2 MB widgets.json crossed Funnel's public ingress at ~0.3 MB/s on
  // 2026-10-18 (18-60+ s), past BDOBB's web layer's 12 s upstream timeout. Its fetch sends
  // Accept-Encoding: gzip and decodes the answer itself.
  const upstream = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(Object.fromEntries(Array.from({ length: 400 }, (_, i) => [`w${i}`, "x".repeat(2500)]))));
  });
  upstream.listen(0, "127.0.0.1"); await once(upstream, "listening");
  t.after(() => new Promise(resolve => upstream.close(resolve)));
  const origin = `http://127.0.0.1:${upstream.address().port}`;
  const { port } = await fixture(t, { apiOrigin: origin, refOrigin: origin }, { requestJson: getJson });
  const gzip = { ...HEADERS, "Accept-Encoding": "gzip, deflate" };
  for (const path of ["/api/widgets.json", "/api/apps.json", "/ref/widgets.json", "/ref/apps.json"]) {
    const packed = await http(port, path, gzip);
    assert.equal(packed.status, 200, path);
    assert.equal(packed.headers["content-encoding"], "gzip", path);
    assert.match(packed.headers.vary ?? "", /Accept-Encoding/, path);
    assert.equal(packed.headers["x-content-type-options"], "nosniff", path);
    assert.ok(packed.body.length < 100_000, `${path} sent ${packed.body.length} bytes`);
    assert.equal(Object.keys(JSON.parse(gunzipSync(packed.body).toString())).length, 400, path);
    const plain = await http(port, path);
    assert.equal(plain.headers["content-encoding"], undefined, path);
    assert.equal(Object.keys(JSON.parse(plain.text)).length, 400, path);
  }
  // A data route is never encoded, whatever the caller accepts.
  const data = await http(port, "/ref/metric_widget", gzip);
  assert.equal(data.headers["content-encoding"], undefined);
});

// Adapted at the release/v11 merge: main's MANIFEST_MAX (16 MiB, every root manifest, both
// upstreams) supersedes the codex branch's v11-only 8 MiB budget, so v10 now admits the same
// catalogue and the oversize probes sit just past 16 MiB.




/**
 * live-grid's own leg of the preflight, as a loopback fixture: it answers /health, behind the
 * SAME Basic pair as openbb-api (its BasicAuthMiddleware wraps its whole app, /health
 * included), and records what it was asked. `grid.status` lets a test make it fail.
 */
async function gridStub(t) {
  // `open` is what a request without the pair gets: 401 from a locked live-grid.
  const grid = { status: 200, open: 401, seen: [] };
  const server = createServer((req, res) => {
    grid.seen.push({ path: req.url, auth: req.headers.authorization });
    res.writeHead(req.headers.authorization ? grid.status : grid.open, { "Content-Type": "application/json" });
    res.end("{}");
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  grid.origin = `http://127.0.0.1:${server.address().port}`;
  return grid;
}



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
  // whole reason this leg carries the pair. Then once WITHOUT it (D26, review 2026-10-16):
  // that must be 401, or live-grid's lock is off and the door must not open.
  assert.deepEqual(grid.seen, [{ path: "/health", auth: cfg.apiAuthorization }, { path: "/health", auth: undefined }]);
  grid.open = 200;
  await assert.rejects(checkUpstreams(cfg), /live-grid lock preflight failed: no credential answered HTTP 200, wanted 401/);
  grid.open = 401;
  // Anything but a 200 stops the door: 401 (the pair is wrong or absent) and 503 (live-grid
  // is up but not ready) are both refusals, not warnings.
  for (const status of [401, 503, 500]) {
    grid.status = status;
    await assert.rejects(checkUpstreams(cfg), new RegExp(`live-grid preflight failed \\(HTTP ${status}\\)`));
  }
});



// ---- Socket tickets: the browser's own sockets (relaying them through a Vercel Function bills function time while they are open).
const PREVIEW = "https://bdobb.example.vercel.app";
const ticketed = (path, ticket) => path + (path.includes("?") ? "&" : "?") + "ticket=" + ticket;
const browser = { Host: new URL(ORIGIN).host, Origin: PREVIEW };





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

test("no ticket is minted while live-grid is off", async t => {
  // D10 (review 2026-10-16): every /grid route answers 503 with liveGrid off; the mint did not.
  const { port } = await fixture(t, { gridOrigin: null });
  assert.equal((await mint(port, "/grid/live_grid_ws", DESKTOP[0])).status, 503);
});

test("a ticket refused for load is not used up; it opens the socket once the slot is free", async t => {
  // D13 (review 2026-10-16): the nonce was recorded before the 429/503 checks, so a refusal
  // for load burned it and the client had to mint again.
  const { port } = await fixture(t, { maxSockets: 1 });
  const path = "/grid/live_grid_ws", desk = { Host: HEADERS.Host, Origin: DESKTOP[0] };
  const ticketOf = async () => JSON.parse((await mint(port, path, DESKTOP[0])).text).ticket;
  const hold = await wsConnect(port, desk, ticketed(path, await ticketOf()));
  assert.equal(hold.status, 101);
  const ticket = await ticketOf();
  assert.equal((await wsConnect(port, desk, ticketed(path, ticket))).status, 429);
  const closed = once(hold.ws, "close"); hold.ws.terminate(); await closed;
  await new Promise(resolve => setTimeout(resolve, 50));
  const opened = await wsConnect(port, desk, ticketed(path, ticket));
  assert.equal(opened.status, 101); opened.ws.terminate();
  // ...and it is still single use.
  assert.equal((await wsConnect(port, desk, ticketed(path, ticket))).status, 401);
});

// ---- The wire's socket: the first route this door serves over a socket (Ep. 8).





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

test("a grid socket's client frames are capped at 60 while it is open", async t => {
  // The one per-socket bound left on the grid: 60 more frames after the first.
  const f = await gridFixture(t);
  const { ws, up } = await gridRelayed(f);
  await within(up, "message");
  const closed = within(ws, "close", 4000);
  const upClosed = within(up, "close", 4000);
  // 60 validated frames a socket: the first plus 59 more are accepted, the 61st closes it.
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

test("a tick chart's pushes are neither capped nor metered: it streams while it is open", async t => {
  const f = await taFixture(t);
  const { ws } = await wsConnect(f.port, undefined, TA_WS);
  const up = await dialled(f);
  // Well past the old 60-push ceiling, every push relayed and the socket still open.
  let got = 0; ws.on("message", () => got++);
  for (let i = 0; i < 100; i++) up.send(`{"rev":${i}}`);
  while (got < 100) await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(ws.readyState, WebSocket.OPEN);
  ws.terminate();
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

test("the grid socket's own first-frame deadline and dead-peer heartbeat are bounded", async t => {
  const first = await fixture(t, {}, { firstFrameMs: 30, openGrid: () => new WebSocket("ws://127.0.0.1:9") });
  const a = await gridConnect(first); await once(a.ws, "close");
  const second = await fixture(t, {}, { firstFrameMs: 1000, pingMs: 20, openGrid: () => new WebSocket("ws://127.0.0.1:9") });
  const b = await deafConnect(second.port, GRID_WS); await within(b, "close");
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















// The stack builds the image compose names, so the package version, the lockfile and the
// compose image tag must agree, or a deploy runs a gateway that predates its own documentation.


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

test("with live-grid off the page is behind the lock again; a failed fetch is held 5 s, then retried", async t => {
  // D12 (review 2026-10-16): an anonymous 503 told any caller the `live` profile was off. With
  // it off the page is not served before the lock: 401 without the token, as at v9, and the
  // grid's own 503 with it.
  const off = await subscriptionsFixture(t, { gridOrigin: null });
  assert.equal((await http(off.port, "/grid/subscriptions", { Host: new URL(ORIGIN).host })).status, 401);
  assert.equal((await http(off.port, "/grid/subscriptions")).status, 503);
  assert.equal(off.fetched.length, 0);
  // D11: a failed fetch used to be retried on the very next anonymous request, one live-grid
  // dial each. It is held for 5 s by the door's clock, then retried.
  let fail = true, clock = 1_000_000; const tries = [];
  const flaky = await fixture(t, {}, { now: () => clock, fetchPage: async () => {
    tries.push(1); if (fail) throw new Error("down"); return "<p>ok</p>";
  } });
  const anon = { Host: new URL(ORIGIN).host };
  for (let i = 0; i < 5; i++) assert.equal((await http(flaky.port, "/grid/subscriptions", anon)).status, 502);
  assert.equal(tries.length, 1);
  fail = false;
  assert.equal((await http(flaky.port, "/grid/subscriptions", anon)).status, 502);
  clock += 5000;
  assert.equal((await http(flaky.port, "/grid/subscriptions", anon)).text, "<p>ok</p>");
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

test("POST rebuilds the body from a validated symbol", async t => {
  const { port, sent } = await subscriptionsFixture(t, {},
    (method) => (method === "POST" ? { status: 201, json: { used: 2, cap: 50 } } : { status: 200, json: {} }));
  const r = await sendBody(port, "/grid/api/subscriptions", { body: JSON.stringify({ symbol: " BTC-USD ", extra: "dropped" }) });
  assert.equal(r.status, 201);
  assert.deepEqual(JSON.parse(r.text), { used: 2, cap: 50 });
  assert.deepEqual(sent, [{ method: "POST", path: "/api/subscriptions", body: JSON.stringify({ symbol: "BTC-USD" }) }]);
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

test("a literal %5E in the one-symbol DELETE path is the caret; every other % still gets 421", async t => {
  // D8 (review 2026-10-16): WHATWG URL parsers percent-encode "^" in a path, so a client may
  // send %5EGSPC. requestUrl refused every "%" before subscriptionRoute could read it.
  const { port, sent } = await subscriptionsFixture(t);
  for (const path of ["/grid/api/subscriptions/%5EGSPC", "/grid/api/subscriptions/%5eDJI"]) {
    assert.equal((await http(port, path, HEADERS, "DELETE")).status, 200, path);
  }
  assert.deepEqual(sent.map(s => [s.method, s.path]),
    [["DELETE", "/api/subscriptions/^GSPC"], ["DELETE", "/api/subscriptions/^DJI"]]);
  for (const [path, method] of [["/grid/api/subscriptions/%5EGSPC%2F", "DELETE"], ["/grid/api/subscriptions/%2e%2e", "DELETE"],
    ["/grid/api/subscriptions/%5E/x", "DELETE"], ["/grid/api/%5Esubscriptions/X", "DELETE"],
    ["/grid/api/subscriptions/%5", "DELETE"], ["/api/api/v1/equity/%5E", "GET"]]) {
    assert.equal((await http(port, path, HEADERS, method)).status, 421, `${method} ${path}`);
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







// v10 walk: the desktop's packaged Origin (V10-P1) reaches the managed table routes as the desktop principal,
// behind the Bearer lock; any other foreign Origin is still refused before anything is relayed.


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































const CHART = "/grid/chart_stream_ws";
const CHART_CONTROL = {protocol_version:1,type:"subscribe",subscription_id:"a",request_id:"r",view:{symbol:"AAPL",mode:"ticks",start:"2026-11-20T14:30:00.000000000Z",max_items:10000}};
test("chart stream: public Vercel ticket is exact-origin bound, single-use, and expiring", async t => {
  const previewOrigin = "https://charts-test.vercel.app";
  const {port} = await fixture(t, {previewOrigin});
  const headers = {Host:HEADERS.Host, Origin:previewOrigin};
  assert.equal((await wsConnect(port, headers, CHART)).status,401);
  const signed = socketTicket(TOKEN, previewOrigin+CHART);
  assert.equal((await wsConnect(port,{...headers,Origin:previewOrigin+".evil.example"},CHART+"?ticket="+signed)).status,403);
  assert.equal((await wsConnect(port,headers,CHART+"?ticket="+socketTicket(TOKEN,CHART))).status,401);
  assert.equal((await wsConnect(port,headers,CHART+"?ticket="+socketTicket(TOKEN,previewOrigin+CHART,Date.now()-31000))).status,401);
  const opened = await wsConnect(port,headers,CHART+"?ticket="+signed);
  assert.equal(opened.status,101); t.after(()=>opened.ws.terminate());
  assert.equal((await wsConnect(port,headers,CHART+"?ticket="+signed)).status,401);
  assert.equal((await wsConnect(port,headers,"/grid/live_grid_ws?ticket="+signed)).status,401);
});
test("chart stream: validated controls relay to named live-grid endpoint", async t => {
  const upstream = new WebSocketServer({port:0,host:"127.0.0.1"}); await once(upstream,"listening");
  t.after(()=>new Promise(resolve=>upstream.close(resolve)));
  let path; const messages=[];
  upstream.on("connection",(ws,req)=>{path=req.url;ws.on("message",data=>{messages.push(JSON.parse(data));ws.send(JSON.stringify({ok:true}));});});
  const {port} = await fixture(t,{}, {openGrid:(_cfg,path)=>new WebSocket(`ws://127.0.0.1:${upstream.address().port}${path}`)});
  const {ws,status} = await wsConnect(port,{...HEADERS,Origin:ORIGIN},CHART);
  assert.equal(status,101); t.after(()=>ws.terminate());
  const next=once(ws,"message"); ws.send(JSON.stringify(CHART_CONTROL)); await next;
  assert.equal(path,"/chart_stream_ws"); assert.deepEqual(messages,[CHART_CONTROL]);
  const closed=once(ws,"close"); ws.send(JSON.stringify({...CHART_CONTROL,type:"execute",source:"delete from ticks"})); await closed;
});
test("chart stream: ticket lease forces fresh authenticated admission",async t=>{
 const previewOrigin='https://charts-test.vercel.app';
 const {port}=await fixture(t,{previewOrigin});
 const signed=socketTicket(TOKEN,previewOrigin+CHART,Date.now()-29800);
 const {ws,status}=await wsConnect(port,{Host:HEADERS.Host,Origin:previewOrigin},CHART+'?ticket='+signed);
 assert.equal(status,101);
 const [code]=await once(ws,'close');
 assert.equal(code,4001);
});
