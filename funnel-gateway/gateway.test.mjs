// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { stateFile } from "./policy.mjs";
import { chmod, mkdtemp, mkdir, readdir, rm, utimes, writeFile } from "node:fs/promises";
import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { validateConfig, readConfig } from "./config.mjs";
import { createGateway, getJson } from "./server.mjs";
import { verify } from "./verify.mjs";
import { checkUpstreams } from "./check-upstreams.mjs";

// Built at run time so the public-content scan never sees a literal tailnet name.
const TAILNET = ["example-tailnet", "ts", "net"].join(".");

const TOKEN = "synthetic_test_credential_not_for_deployment";
const ORIGIN = `https://openbq.${TAILNET}:10000`;
// openbq-docker serves no /ai (Rita), and the wire (/news) arrives at v8: their settings are
// unknown keys and their routes unmatched (tests below).
const settings = { origin: ORIGIN, quoteDailyLimit: 100 };
const secrets = { token: TOKEN, apiUsername: "testuser", apiPassword: "synthetic-password" };
const config = () => validateConfig(settings, secrets);
const HEADERS = { Host: new URL(ORIGIN).host, Authorization: `Bearer ${TOKEN}` };
const quote = "/api/api/v1/equity/price/quote?symbol=AAPL&provider=eodhd";
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
    { maxConcurrent: 0 }, { maxConcurrent: 33 },
    { stateDir: "relative/state" }, { stateDir: "/var/lib/../etc" }, { stateDir: 7 }, { stateDir: "" },
    // Settings of later lines are not silently accepted: a stack at this tag has no such upstream.
    { gridOrigin: "http://openbb-live-grid:6903" }, { tickUrl: `wss://kdb.${TAILNET}` }, { liveGrid: true },
    // The wire and the socket door arrive at v8: their keys are unknown here.
    { rssOrigin: `https://openbq.${TAILNET}:8088` }, { rssAddress: [100, 64, 0, 3].join(".") },
    { feeds: {} }, { previewOrigin: "https://bdobb.example.vercel.app" }, { maxSockets: 4 },
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
  assert.deepEqual([defaults.requestsPerMinute, defaults.maxConcurrent, defaults.stateDir], [60, 8, null]);
  for (const key of ["ritaOrigin", "ritaAddress", "socksProxy", "rssOrigin", "rssAddress", "feeds", "previewOrigin", "maxSockets"]) {
    assert.equal(key in defaults, false, key);
  }
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
// validate, not merely look plausible.
test("the shipped settings.example.json validates as-is", () => {
  const example = JSON.parse(readFileSync(new URL("./settings.example.json", import.meta.url), "utf8"));
  const cfg = validateConfig(example, secrets);
  // The example names YOUR-TAILNET (the repo's placeholder); a URL origin is lowercase.
  assert.equal(cfg.origin, example.origin.toLowerCase());
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

test("only bounded OpenBB queries reach upstream; later families are refused", async t => {
  const { port, calls } = await fixture(t);
  for (const path of ["/", "/tick", "/keys", "/mcp", "/stores", "/live/widgets.json",
    "/grid/widgets.json", quote + "&symbol=MSFT",
    // The wire arrives at v8: nothing under /news/ is a route here.
    "/news/api/news?feed_id=7&limit=1", "/news/ws/news", "/news/admin"]) {
    assert.equal((await http(port, path)).status, 404, path);
  }
  // openbq-docker serves no /ai (Rita): her document is unmatched, and her POST is not a route.
  for (const path of ["/ai/agents.json", "/ai/v1/query", "/ai/other"]) assert.equal((await http(port, path)).status, 404, path);
  assert.equal((await http(port, "/ai/v1/query", HEADERS, "POST")).status, 405);
  assert.equal((await http(port, quote)).status, 200);
  assert.deepEqual(calls.map(c => c.path), [quote]);
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
  for (const bad of ["/ref/omni-sql-widget", "/ref/assets/other.svg", "/ref/metric_widget.json"]) {
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

test("operator verifier makes no upstream or provider calls", async t => {
  const { port, calls } = await fixture(t);
  await verify(config(), `http://127.0.0.1:${port}`); assert.equal(calls.length, 0);
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
  const cfg = { ...config(), apiOrigin: `http://127.0.0.1:${upstream.address().port}` };
  await checkUpstreams(cfg);
  assert.deepEqual(seen, [{ path: "/api/v1/equity/price/quote", auth: cfg.apiAuthorization },
    { path: "/api/v1/equity/price/quote", auth: undefined }]);
  withPair = 401; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  withPair = 200; await assert.rejects(checkUpstreams(cfg), /API auth preflight failed/);
  // OPENBB_API_AUTH off: the pair is "accepted" because nothing is checked. The door stays shut.
  withPair = 422; withoutPair = 422; await assert.rejects(checkUpstreams(cfg), /API lock preflight failed/);
});

// ---- No socket route at this tag: the wire's (/news/ws/news) arrives at v8.
function upgrade(port, headers, path = "/news/ws/news") {
  return http(port, path, { ...headers, Connection: "Upgrade", Upgrade: "websocket",
    "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==" });
}
test("every upgrade is refused: 401 without the token, 404 with it", async t => {
  const { port, calls } = await fixture(t);
  for (const path of ["/news/ws/news", "/grid/live_grid_ws", "/state/42", "/nope"]) {
    assert.equal((await upgrade(port, { Host: HEADERS.Host, Origin: ORIGIN }, path)).status, 401, path);
    assert.equal((await upgrade(port, { ...HEADERS, Origin: ORIGIN }, path)).status, 404, path);
    for (const origin of DESKTOP) assert.equal((await upgrade(port, { ...HEADERS, Origin: origin }, path)).status, 404, path);
  }
  assert.equal(calls.length, 0);
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
// compose image tag (wired in a later task) must agree, or a deploy runs a gateway that predates its own documentation.
test("the package version is this release", () => {
  const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
  const lock = JSON.parse(readFileSync(new URL("./package-lock.json", import.meta.url), "utf8"));
  assert.equal(lock.version, version);
  assert.match(readFileSync(new URL("./README.md", import.meta.url), "utf8"), new RegExp(`v${version.replaceAll(".", "\\.")}`));
});
