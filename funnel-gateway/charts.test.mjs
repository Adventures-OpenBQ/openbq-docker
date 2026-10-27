// funnel-gateway/charts.test.mjs
// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { WebSocket, WebSocketServer } from "ws";
import { validateConfig } from "./config.mjs";
import { createGateway } from "./server.mjs";
import { chartsRoute, chartsTokenRoute, chartsSocketTarget, chartsStatus, ntfyRoute } from "./charts-policy.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const id2 = "22222222-2222-4222-8222-222222222222";
const token = "synthetic_gateway_token_only_for_tests";
const ORIGIN = "https://" + ["fixture", "example", "ts", "net"].join(".") + ":10000";
const settings = { origin: ORIGIN };
const secrets = { token, apiUsername: "fixture", apiPassword: "fixture" };
const PAIR = "Basic " + Buffer.from("fixture:fixture").toString("base64");
const LINK = "eyJpdGVtIjoiMSJ9.abcdefghijklmnopqrstuv";
const u = path => new URL(path, ORIGIN);

test("every listed /charts route is admitted exactly, with its query keys", () => {
  for (const [method, path, kind] of [
    ["GET", "/charts", "json"], ["POST", "/charts", "json"], ["GET", "/charts/events", "sse"],
    ["POST", "/charts/mcp", "mcp"], ["GET", `/charts/${id}`, "json"], ["PUT", `/charts/${id}`, "json"],
    ["DELETE", `/charts/${id}`, "json"], ["GET", `/charts/${id}/history`, "json"],
    ["POST", `/charts/${id}/restore/3`, "json"], ["GET", `/charts/${id}/snapshot.png?width=1200&height=675&theme=light`, "png"],
    ["GET", `/charts/${id}/snapshots/${id2}.png`, "png"],
    ["GET", "/series?symbol=AAPL&interval=5m&start=2026-10-01&provider=yfinance&session=regular", "json"],
    ["GET", "/ta_registry", "json"], ["GET", "/ta_macros", "json"],
    ["GET", "/ta_snapshot?symbol=CL%3DF&interval=1d&macro=classic-momentum&indicators=rsi:period=14&warmup=auto&fresh=true", "json"],
    ["GET", "/inbox?limit=50&before=WyIyMDI2Il0", "json"], ["GET", `/inbox/${id}`, "json"], ["DELETE", `/inbox/${id}`, "json"],
    ["GET", `/inbox/${id}/snapshots/0.png`, "png"], ["POST", `/inbox/${id}/read`, "json"],
    ["GET", `/watches?chart_id=${id}`, "json"], ["GET", "/schedules", "json"],
  ]) {
    const route = chartsRoute(u(path), method);
    assert.equal(route?.kind, kind, `${method} ${path}`);
    const parsed = u(path);
    assert.equal(route.path, parsed.pathname + (parsed.search ? "?" + parsed.searchParams.toString() : ""), `${method} ${path}`);
  }
  assert.equal(chartsRoute(u("/charts"), "POST").body, true);
  assert.equal(chartsRoute(u(`/charts/${id}/restore/3`), "POST").body, false);
  assert.equal(chartsRoute(u(`/inbox/${id}/read`), "POST").body, false);
});

test("unlisted routes, methods, keys, values and path tricks are refused", () => {
  for (const [method, path] of [
    ["GET", "/charts/"], ["GET", `/charts/${id}/`], ["GET", `/charts/${"abcdefab-abcd-4bcd-8bcd-abcdefabcdef".toUpperCase()}`], ["GET", "/charts/not-a-uuid"],
    ["PATCH", `/charts/${id}`], ["GET", "/charts?x=1"], ["GET", "/charts/mcp"], ["POST", "/charts/events"],
    ["GET", `/charts/${id}/snapshot.png?width=99`], ["GET", `/charts/${id}/snapshot.png?theme=blue`],
    ["GET", `/charts/${id}/restore/3`], ["POST", `/charts/${id}/restore/0`],
    ["GET", "/series?symbol=AAPL&symbol=MSFT"], ["GET", "/series?macro=x"], ["GET", "/series?provider=kdb"],
    ["GET", "/series?interval=1y"], ["GET", "/series?symbol=A%0AB"], ["GET", "/series?start=T-1bd"],
    ["GET", "/ta_snapshot?indicators=rsi%20x"], ["GET", "/inbox?limit=201"], ["GET", "/inbox?limit=0"],
    ["GET", `/inbox/${id}?t=${LINK}`], ["POST", "/inbox"], ["POST", "/watches"], ["POST", "/schedules"],
    ["DELETE", `/watches/${id}`], ["GET", "/watches?chart_id=x"], ["POST", "/watches/action"],
    ["GET", "/ta_series_ws"], ["GET", "/charts/ws_ticket?target=/ta_series_ws"], ["GET", "/docs"],
  ]) assert.equal(chartsRoute(u(path), method), null, `${method} ${path}`);
});

test("only the three token routes pass without the gateway token, each only in its exact shape", () => {
  for (const [method, path] of [["GET", `/inbox/${id}?t=${LINK}`], ["GET", `/inbox/${id}/snapshots/2.png?t=${LINK}`],
                                ["POST", "/watches/action"]]) {
    assert.ok(chartsTokenRoute(u(path), method), `${method} ${path}`);
  }
  for (const [method, path] of [["GET", `/inbox/${id}`], ["GET", `/inbox/${id}?t=${LINK}&t=${LINK}`],
                                ["GET", `/inbox/${id}?t=${LINK}&limit=1`], ["GET", `/inbox/${id}?t=bad token`],
                                ["DELETE", `/inbox/${id}?t=${LINK}`], ["POST", "/watches/action?x=1"],
                                ["GET", "/watches/action"], ["GET", `/charts/${id}?t=${LINK}`], ["GET", `/inbox?t=${LINK}`]]) {
    assert.equal(chartsTokenRoute(u(path), method), null, `${method} ${path}`);
  }
});

test("the study socket's target is /ta_snapshot's grammar without fresh", () => {
  assert.equal(chartsSocketTarget("/ta_series_ws", ORIGIN), "/ta_series_ws");
  assert.equal(chartsSocketTarget("/ta_series_ws?symbol=AAPL&interval=1d&macro=none&indicators=rsi:period=14", ORIGIN),
               "/ta_series_ws?symbol=AAPL&interval=1d&macro=none&indicators=rsi%3Aperiod%3D14");
  for (const raw of ["/ta_series_ws?fresh=true", "/ta_series_ws?provider=x", "/ta_series_ws/", "//ta_series_ws",
                     "/ta_%73eries_ws", "/grid/ta_chart_ws", "/ta_series_ws#x", "https://evil.test/ta_series_ws", 7]) {
    assert.equal(chartsSocketTarget(raw, ORIGIN), null, String(raw));
  }
});

test("charts is an explicit boolean with a fixed origin", () => {
  assert.equal(validateConfig(settings, secrets).chartsOrigin, null);
  assert.equal(validateConfig({ ...settings, charts: true }, secrets).chartsOrigin, "http://arts-charts:8000");
  for (const charts of ["true", 1, null]) assert.throws(() => validateConfig({ ...settings, charts }, secrets));
  assert.throws(() => validateConfig({ ...settings, chartsOrigin: "http://evil.test" }, secrets));
});

test("only semantic statuses survive", () => {
  for (const s of [200, 201, 202, 204, 400, 401, 404, 409, 413, 415, 422, 428, 429, 503]) assert.equal(chartsStatus(s), s);
  for (const s of [301, 403, 418, 500, 502, 504]) assert.equal(chartsStatus(s), 502);
});
async function listen(server) { server.listen(0, "127.0.0.1"); await once(server, "listening"); return "http://127.0.0.1:" + server.address().port; }
function call(port, path, { method = "GET", body, headers = {}, bearer = true } = {}) {
  return new Promise((resolve, reject) => {
    const req = request({ hostname: "127.0.0.1", port, path, method,
      headers: { host: new URL(ORIGIN).host, ...(bearer ? { authorization: "Bearer " + token } : {}), ...headers } }, res => {
      const chunks = []; res.on("data", c => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject); req.end(body);
  });
}
async function stack(t, handler, change = {}, options = {}) {
  const seen = [];
  const upstream = createServer((req, res) => { let body = ""; req.on("data", c => body += c);
    req.on("end", () => { seen.push({ method: req.method, path: req.url, headers: req.headers, body }); handler(req, res); }); });
  const chartsOrigin = await listen(upstream);
  t.after(() => { upstream.closeAllConnections(); return new Promise(r => upstream.close(r)); });
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true, ...change }, secrets), chartsOrigin }, options);
  await listen(gateway); t.after(() => gateway.closeGateway());
  return { port: gateway.address().port, seen, upstream };
}
const json = (res, status, value, extra = {}) => { res.writeHead(status, { "Content-Type": "application/json", ...extra }); res.end(JSON.stringify(value)); };

test("REST: pair injected, If-Match kept, caller headers dropped, 409 body relayed, 500 hidden", async t => {
  const { port, seen } = await stack(t, (req, res) =>
    req.method === "PUT" ? json(res, 409, { id, revision: 4 }, { "Set-Cookie": "x=y" }) : json(res, 500, { secret: "leak" }));
  const put = await call(port, `/charts/${id}`, { method: "PUT", body: '{"title":"A","body":{}}',
    headers: { "content-type": "application/json", "if-match": '"3"', "x-updated-by": "rita", cookie: "c=1" } });
  assert.equal(put.status, 409); assert.deepEqual(JSON.parse(put.body), { id, revision: 4 });
  assert.equal(put.headers["set-cookie"], undefined);
  assert.equal(seen[0].path, `/charts/${id}`); assert.equal(seen[0].headers.authorization, PAIR);
  assert.equal(seen[0].headers["if-match"], '"3"');
  assert.equal(seen[0].headers["x-updated-by"], undefined); assert.equal(seen[0].headers.cookie, undefined);
  const hidden = await call(port, "/charts");
  assert.equal(hidden.status, 502); assert.doesNotMatch(hidden.body.toString(), /leak/);
  assert.equal((await call(port, `/charts/${id}`, { method: "PUT", body: "{}", headers: { "content-type": "application/json", "if-match": "x" } })).status, 400);
});

test("token-only routes forward no credential, need no gateway token, and nothing else does", async t => {
  const { port, seen } = await stack(t, (req, res) => req.url.endsWith(".png?t=" + LINK)
    ? (res.writeHead(200, { "Content-Type": "image/png" }), res.end(Buffer.from([0x89, 0x50, 0x4e, 0x47])))
    : json(res, 200, { ok: true }));
  for (const [path, opts] of [[`/inbox/${id}?t=${LINK}`, {}], [`/inbox/${id}/snapshots/0.png?t=${LINK}`, {}],
                              ["/watches/action", { method: "POST", body: '{"action":"x"}', headers: { "content-type": "application/json" } }]]) {
    const answer = await call(port, path, { ...opts, bearer: false });
    assert.equal(answer.status, 200, path);
  }
  assert.deepEqual(seen.map(s => s.headers.authorization), [undefined, undefined, undefined]);
  // A caller's own Authorization is not forwarded either.
  await call(port, `/inbox/${id}?t=${LINK}`, { bearer: false, headers: { authorization: PAIR } });
  assert.equal(seen.at(-1).headers.authorization, undefined);
  const count = seen.length;
  for (const path of [`/inbox/${id}`, "/charts", `/charts/${id}?t=${LINK}`, "/watches/action?x=1"])
    assert.equal((await call(port, path, { bearer: false })).status, 401, path);
  assert.equal(seen.length, count);
});

test("an empty-body upstream 401 is a 401 on a token-only route and a 502 on a credentialed one", async t => {
  const { port } = await stack(t, (req, res) => { res.writeHead(401); res.end(); });
  assert.equal((await call(port, `/inbox/${id}?t=${LINK}`, { bearer: false })).status, 401);
  assert.equal((await call(port, `/inbox/${id}/snapshots/0.png?t=${LINK}`, { bearer: false })).status, 401);
  assert.equal((await call(port, `/inbox/${id}`)).status, 502);
});

test("the token-only POST /watches/action is capped at 8 KiB; credentialed routes keep 1 MiB", async t => {
  const { port, seen } = await stack(t, (req, res) => json(res, 200, { ok: true }));
  const post = (path, size, bearer) => call(port, path, { method: "POST", bearer,
    body: JSON.stringify({ token: "x".repeat(size) }), headers: { "content-type": "application/json" } });
  assert.equal((await post("/watches/action", 8 * 1024 - 64, false)).status, 200);
  assert.equal((await post("/watches/action", 8 * 1024, false)).status, 413);
  assert.equal(seen.length, 1);
  assert.equal((await post("/charts", 100 * 1024, true)).status, 200);
});

test("a PNG is relayed as image/png with its revision; a slow PNG outlives requestMs", async t => {
  const { port } = await stack(t, (req, res) => setTimeout(() => {
    res.writeHead(200, { "Content-Type": "image/png", "X-Chart-Revision": "7" }); res.end(Buffer.alloc(3 * 1024 * 1024, 1));
  }, 300), {}, { requestMs: 50 });
  const png = await call(port, `/charts/${id}/snapshot.png?theme=dark`);
  assert.equal(png.status, 200); assert.equal(png.headers["content-type"], "image/png");
  assert.equal(png.headers["x-chart-revision"], "7"); assert.equal(png.body.length, 3 * 1024 * 1024);
});

test("the SSE feed is streamed, counts against maxSockets and frees its slot", async t => {
  const { port } = await stack(t, (req, res) => { res.writeHead(200, { "Content-Type": "text/event-stream" }); res.write("retry: 1000\n\n"); }, { maxSockets: 1 });
  const first = request({ hostname: "127.0.0.1", port, path: "/charts/events", headers: { host: new URL(ORIGIN).host, authorization: "Bearer " + token } });
  first.end(); const [response] = await once(first, "response");
  assert.equal(response.headers["content-type"], "text/event-stream; charset=utf-8");
  const [chunk] = await once(response, "data"); assert.match(chunk.toString(), /retry: 1000/);
  assert.equal((await call(port, "/charts/events")).status, 429);
  first.destroy(); await new Promise(r => setTimeout(r, 50));
  const again = request({ hostname: "127.0.0.1", port, path: "/charts/events", headers: { host: new URL(ORIGIN).host, authorization: "Bearer " + token } });
  again.end(); const [ok] = await once(again, "response"); assert.equal(ok.statusCode, 200); again.destroy();
});

test("/charts/mcp is rate-limited per principal at 600 an hour", async t => {
  const { port } = await stack(t, (req, res) => json(res, 200, { jsonrpc: "2.0", id: 1, result: {} }));
  const message = { method: "POST", body: '{"jsonrpc":"2.0","id":1,"method":"tools/list"}', headers: { "content-type": "application/json" } };
  for (let i = 0; i < 600; i++) assert.equal((await call(port, "/charts/mcp", message)).status, 200);
  assert.equal((await call(port, "/charts/mcp", message)).status, 429);
  assert.equal((await call(port, "/charts/mcp", { ...message, headers: { ...message.headers, "x-preview-principal": "github:7" } })).status, 200);
});

test("charts off answers exactly as v11", async t => {
  const gateway = createGateway(validateConfig(settings, secrets)); await listen(gateway); t.after(() => gateway.closeGateway());
  const port = gateway.address().port;
  for (const path of ["/charts", `/charts/${id}`, "/series?symbol=AAPL", "/charts/events", `/inbox/${id}`, "/charts/ws_ticket?target=/ta_series_ws"])
    assert.equal((await call(port, path)).status, 404, path);
  for (const [method, path] of [["POST", "/charts/mcp"], ["PUT", `/charts/${id}`], ["POST", "/watches/action"]])
    assert.equal((await call(port, path, { method, body: "{}", headers: { "content-type": "application/json" } })).status, 405, path);
  for (const path of [`/inbox/${id}?t=${LINK}`, "/watches/action"]) assert.equal((await call(port, path, { bearer: false })).status, 401, path);
});

test("the study socket: pair injected on the upgrade, push-only, a 1 MiB study frame is relayed", async t => {
  const big = JSON.stringify({ type: "series", candles: "x".repeat(1024 * 1024) });
  const heard = [];
  const wss = new WebSocketServer({ port: 0, host: "127.0.0.1" }); await once(wss, "listening");
  wss.on("connection", (socket, req) => { heard.push(req); socket.send(big); });
  t.after(() => new Promise(r => wss.close(r)));
  const chartsOrigin = "http://127.0.0.1:" + wss.address().port;
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true }, secrets), chartsOrigin }); await listen(gateway);
  t.after(() => gateway.closeGateway());
  const client = new WebSocket(`ws://127.0.0.1:${gateway.address().port}/ta_series_ws?symbol=AAPL&interval=1d`,
    { headers: { host: new URL(ORIGIN).host, authorization: "Bearer " + token, origin: ORIGIN }, maxPayload: 8 * 1024 * 1024 });
  const [data] = await once(client, "message");
  assert.equal(data.length, big.length);
  assert.equal(heard[0].headers.authorization, PAIR); assert.equal(heard[0].url, "/ta_series_ws?symbol=AAPL&interval=1d");
  client.send("{}"); await once(client, "close");
});

test("/charts/ws_ticket: desktop Origin only, target checked, ticket opens the socket once", async t => {
  const wss = new WebSocketServer({ port: 0, host: "127.0.0.1" }); await once(wss, "listening"); wss.on("connection", s => s.send('{"type":"series"}'));
  t.after(() => new Promise(r => wss.close(r)));
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true }, secrets), chartsOrigin: "http://127.0.0.1:" + wss.address().port });
  await listen(gateway); t.after(() => gateway.closeGateway()); const port = gateway.address().port;
  const target = "/ta_series_ws?symbol=AAPL";
  assert.equal((await call(port, "/charts/ws_ticket?target=" + encodeURIComponent(target))).status, 403);
  assert.equal((await call(port, "/charts/ws_ticket?target=" + encodeURIComponent("/grid/live_grid_ws"), { headers: { origin: "tauri://localhost" } })).status, 404);
  const issued = await call(port, "/charts/ws_ticket?target=" + encodeURIComponent(target), { headers: { origin: "tauri://localhost" } });
  const { ticket } = JSON.parse(issued.body);
  const url = `ws://127.0.0.1:${port}${target}&ticket=${ticket}`;
  const ok = new WebSocket(url, { headers: { host: new URL(ORIGIN).host, origin: "tauri://localhost" } });
  await once(ok, "message"); ok.close();
  const replay = new WebSocket(url, { headers: { host: new URL(ORIGIN).host, origin: "tauri://localhost" } });
  const [error] = await once(replay, "error"); assert.match(String(error), /401/);
});

test("a study frame past the 4 MiB cap closes the relay", async t => {
  const big = JSON.stringify({ type: "series", candles: "x".repeat(4 * 1024 * 1024 + 1) });
  const wss = new WebSocketServer({ port: 0, host: "127.0.0.1", maxPayload: 16 * 1024 * 1024 }); await once(wss, "listening");
  wss.on("connection", socket => socket.send(big));
  t.after(() => new Promise(r => wss.close(r)));
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true }, secrets), chartsOrigin: "http://127.0.0.1:" + wss.address().port });
  await listen(gateway); t.after(() => gateway.closeGateway());
  const client = new WebSocket(`ws://127.0.0.1:${gateway.address().port}/ta_series_ws?symbol=AAPL&interval=1d`,
    { headers: { host: new URL(ORIGIN).host, authorization: "Bearer " + token, origin: ORIGIN }, maxPayload: 16 * 1024 * 1024 });
  const messages = []; client.on("message", m => messages.push(m)); client.on("error", () => {});
  await once(client, "close");
  assert.equal(messages.length, 0);
});

test("timeouts: a PNG waits 110 s, an MCP message 120 s, other JSON requestMs", async t => {
  const { port } = await stack(t, (req, res) => req.url.includes(".png") || req.url.endsWith("/mcp")
    ? (req.url.includes(".png") ? (res.writeHead(200, { "Content-Type": "image/png" }), res.end(Buffer.from([1]))) : json(res, 200, { jsonrpc: "2.0", id: 1, result: {} }))
    : json(res, 200, []), {}, { requestMs: 4321 });
  const delays = [], real = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms, ...rest) => { delays.push(ms); return real(fn, ms, ...rest); };
  t.after(() => { globalThis.setTimeout = real; });
  await call(port, `/charts/${id}/snapshot.png`);
  assert.ok(delays.includes(110000)); assert.ok(!delays.includes(120000));
  await call(port, "/charts/mcp", { method: "POST", body: '{"jsonrpc":"2.0","id":1,"method":"tools/list"}', headers: { "content-type": "application/json" } });
  assert.ok(delays.includes(120000));
  await call(port, "/charts");
  assert.ok(delays.includes(4321));
});

test("/ntfy: the one topic's subscribe endpoints only", () => {
  assert.deepEqual(ntfyRoute(u("/ntfy/alerts/json?poll=1&since=all"), "GET", "alerts"), { kind: "json", path: "/alerts/json?poll=1&since=all" });
  assert.deepEqual(ntfyRoute(u("/ntfy/alerts/ws?since=abcdefABCDEF"), "GET", "alerts"), { kind: "ws", path: "/alerts/ws?since=abcdefABCDEF" });
  for (const [method, path, topic] of [["GET", "/ntfy/other/json", "alerts"], ["POST", "/ntfy/alerts", "alerts"],
    ["PUT", "/ntfy/alerts/json", "alerts"], ["GET", "/ntfy/alerts/sse", "alerts"], ["GET", "/ntfy/v1/account", "alerts"],
    ["GET", "/ntfy/alerts/json?auth=x", "alerts"], ["GET", "/ntfy/alerts/json?poll=2", "alerts"],
    ["GET", "/ntfy/alerts/json/", "alerts"], ["GET", "/ntfy/alerts/json", null]])
    assert.equal(ntfyRoute(u(path), method, topic), null, `${method} ${path}`);
});

test("ntfyTopic needs charts and a topic-shaped name", () => {
  assert.equal(validateConfig({ ...settings, charts: true, ntfyTopic: "alerts" }, secrets).ntfyOrigin, "http://ntfy:2586");
  assert.equal(validateConfig({ ...settings, charts: true }, secrets).ntfyOrigin, null);
  for (const change of [{ ntfyTopic: "alerts" }, { charts: true, ntfyTopic: "a/b" }, { charts: true, ntfyTopic: "" }])
    assert.throws(() => validateConfig({ ...settings, ...change }, secrets), JSON.stringify(change));
});

test("/ntfy JSON stream: no gateway token, the caller's Authorization forwarded, nothing injected, slot freed", async t => {
  const seen = [];
  const upstream = createServer((req, res) => { seen.push(req); res.writeHead(200, { "Content-Type": "application/x-ndjson" });
    res.write('{"event":"open"}\n'); if (req.url.includes("poll=1")) res.end(); });
  const ntfyOrigin = await listen(upstream); t.after(() => { upstream.closeAllConnections(); return new Promise(r => upstream.close(r)); });
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true, ntfyTopic: "alerts", maxSockets: 1 }, secrets), ntfyOrigin });
  await listen(gateway); t.after(() => gateway.closeGateway()); const port = gateway.address().port;
  const phone = "Basic " + Buffer.from("phone:pw").toString("base64");
  const first = request({ hostname: "127.0.0.1", port, path: "/ntfy/alerts/json", headers: { host: new URL(ORIGIN).host, authorization: phone } });
  first.end(); const [response] = await once(first, "response"); assert.equal(response.statusCode, 200);
  assert.equal(seen[0].url, "/alerts/json"); assert.equal(seen[0].headers.authorization, phone);
  assert.equal((await call(port, "/ntfy/alerts/json", { bearer: false, headers: { authorization: phone } })).status, 429);
  first.destroy(); await new Promise(r => setTimeout(r, 50));
  assert.equal((await call(port, "/ntfy/alerts/json?poll=1", { bearer: false, headers: { authorization: phone } })).status, 200);
  assert.equal((await call(port, "/ntfy/alerts/json", { bearer: false })).status, 401);   // no account: refused at the door
  assert.equal((await call(port, "/ntfy/other/json", { bearer: false, headers: { authorization: phone } })).status, 404);
});

test("/ntfy websocket: the caller's Authorization goes upstream, a client frame closes it", async t => {
  const heard = [];
  const wss = new WebSocketServer({ port: 0, host: "127.0.0.1" }); await once(wss, "listening");
  wss.on("connection", (s, req) => { heard.push(req); s.send('{"event":"open"}'); });
  t.after(() => new Promise(r => wss.close(r)));
  const gateway = createGateway({ ...validateConfig({ ...settings, charts: true, ntfyTopic: "alerts" }, secrets), ntfyOrigin: "http://127.0.0.1:" + wss.address().port });
  await listen(gateway); t.after(() => gateway.closeGateway());
  const phone = "Bearer tk_phonetokenfixture000000000";
  const client = new WebSocket(`ws://127.0.0.1:${gateway.address().port}/ntfy/alerts/ws`, { headers: { host: new URL(ORIGIN).host, authorization: phone } });
  await once(client, "message");
  assert.equal(heard[0].headers.authorization, phone); assert.equal(heard[0].url, "/alerts/ws");
  client.send("x"); await once(client, "close");
});
