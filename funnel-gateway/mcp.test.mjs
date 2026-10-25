// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// The /mcp family on the door: off by default, then one POST route to openbq-mcp, its messages
// filtered (mcp-policy.mjs), its session bound to the principal that opened it, and its limits.

import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { validateConfig } from "./config.mjs";
import { createGateway } from "./server.mjs";
import { verify } from "./verify.mjs";
import { checkMcp } from "./check-upstreams.mjs";

const TAILNET = ["example-tailnet", "ts", "net"].join(".");
const TOKEN = "synthetic_test_credential_not_for_deployment";
const ORIGIN = `https://openbq.${TAILNET}:10000`;
const secrets = { token: TOKEN, apiUsername: "testuser", apiPassword: "synthetic-password" };
const HEADERS = { Host: new URL(ORIGIN).host, Authorization: `Bearer ${TOKEN}` };
const INIT = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "0" } } });
const LIST = JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" });

test("MCP is off by default and its settings fail closed", () => {
  assert.equal(validateConfig({ origin: ORIGIN }, secrets).mcpUpstream, null);
  const on = validateConfig({ origin: ORIGIN, mcp: true }, secrets);
  assert.deepEqual([on.mcpUpstream, on.mcpPerHour], ["http://openbq-mcp:6901", 600]);
  assert.equal(validateConfig({ origin: ORIGIN, mcp: true, mcpPerHour: 5 }, secrets).mcpPerHour, 5);
  for (const change of [{ mcp: "true" }, { mcpPerHour: 5 }, { mcp: true, mcpPerHour: 0 }, { mcp: true, mcpPerHour: 100001 }]) {
    assert.throws(() => validateConfig({ origin: ORIGIN, ...change }, secrets), JSON.stringify(change));
  }
});

/** A stand-in openbq-mcp: records what reached it; initialize opens a session. */
async function fakeMcp(t, answer) {
  const seen = []; let n = 0;
  const server = createServer(async (req, res) => {
    const parts = []; for await (const p of req) parts.push(p);
    const body = Buffer.concat(parts).toString();
    seen.push({ method: req.method, url: req.url, headers: req.headers, body });
    if (answer) return answer(req, res, body);
    const message = JSON.parse(body);
    if (message.id === undefined) { res.writeHead(202); return res.end(); }
    const headers = { "Content-Type": "text/event-stream", ...(message.method === "initialize" ? { "Mcp-Session-Id": `s${++n}` } : {}) };
    res.writeHead(200, headers);
    res.end(`event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: message.id, result: { ok: message.method } })}\n\n`);
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { origin: `http://127.0.0.1:${server.address().port}`, seen };
}
async function door(t, mcp, overrides = {}, dependencies = {}) {
  const config = { ...validateConfig({ origin: ORIGIN, mcp: true }, secrets), mcpUpstream: mcp.origin, ...overrides };
  const server = createGateway(config, { requestJson: async () => ({}), ...dependencies });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  return server.address().port;
}
function post(port, body, headers = {}, path = "/mcp") {
  return new Promise((resolve, reject) => {
    const h = { ...HEADERS, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), ...headers };
    const req = request({ host: "127.0.0.1", port, path, method: "POST", headers: h }, res => {
      const parts = []; res.on("data", c => parts.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(parts).toString() }));
    });
    req.on("error", error => { if (error.code !== "EPIPE") reject(error); }); req.end(body);
  });
}
const as = (who, extra = {}) => ({ "X-Preview-Principal": who, ...extra });

test("off: /mcp answers as a door without it", async t => {
  const server = createGateway(validateConfig({ origin: ORIGIN }, secrets), { requestJson: async () => ({}) });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  assert.equal((await post(server.address().port, INIT)).status, 405);
});

test("initialize opens a session; its id comes back and later calls carry it", async t => {
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp);
  const opened = await post(port, INIT, as("github:42", { Cookie: "a=b", "MCP-Protocol-Version": "2025-06-18" }));
  assert.equal(opened.status, 200);
  assert.match(opened.headers["content-type"], /^text\/event-stream/);
  assert.equal(opened.headers["mcp-session-id"], "s1");
  assert.match(opened.text, /"ok":"initialize"/);
  const listed = await post(port, LIST, as("github:42", { "Mcp-Session-Id": "s1", "MCP-Protocol-Version": "2025-06-18" }));
  assert.equal(listed.status, 200);
  assert.equal(mcp.seen[1].headers["mcp-session-id"], "s1");
  assert.equal(mcp.seen[1].headers["mcp-protocol-version"], "2025-06-18");
  assert.equal(mcp.seen[0].url, "/mcp");
  for (const name of ["authorization", "cookie", "x-preview-principal"]) assert.equal(mcp.seen[0].headers[name], undefined, name);
  const note = await post(port, JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }), as("github:42", { "Mcp-Session-Id": "s1" }));
  assert.equal(note.status, 202);
});

test("a session belongs to the principal that opened it", async t => {
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp);
  await post(port, INIT, as("github:42"));
  const before = mcp.seen.length;
  assert.equal((await post(port, LIST, as("github:7", { "Mcp-Session-Id": "s1" }))).status, 404, "another user's session");
  assert.equal((await post(port, LIST, as("github:42", { "Mcp-Session-Id": "never-opened" }))).status, 404, "an unknown session");
  assert.equal((await post(port, LIST, as("github:42", { "Mcp-Session-Id": "bad id" }))).status, 400);
  assert.equal((await post(port, LIST, as("github:42", { "MCP-Protocol-Version": "latest" }))).status, 400);
  assert.equal(mcp.seen.length, before);
});

test("refused messages never reach openbq-mcp", async t => {
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp);
  const call = (name, args) => JSON.stringify({ jsonrpc: "2.0", id: 9, method: "tools/call", params: { name, arguments: args } });
  for (const body of [call("install_skill", { name: "x" }), call("run_pipeline", { steps: [] }),
    call("call_tool", { name: "tmx_index_document_view", arguments: { url: "http://x/" } }),
    JSON.stringify([{ jsonrpc: "2.0", id: 1, method: "ping" }]), JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sampling/createMessage" }), "{"]) {
    assert.equal((await post(port, body, as("github:42"))).status, 400, body);
  }
  assert.equal((await post(port, INIT, as("github:42", { "Content-Type": "text/plain" }))).status, 415);
  assert.equal((await post(port, JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping", params: { x: "y".repeat(1024 * 1024) } }), as("github:42"))).status, 413);
  assert.equal(mcp.seen.length, 0);
  assert.equal((await post(port, call("call_tool", { name: "equity_price_quote", arguments: { symbol: "AAPL" } }), as("github:42"))).status, 200);
});

test("only POST /mcp is a route, behind the lock", async t => {
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp);
  for (const path of ["/mcp/", "/mcp/mcp", "/mcp?x=1"]) assert.equal((await post(port, INIT, as("github:42"), path)).status, 404, path);
  assert.equal((await post(port, INIT, as("github:42", { Authorization: "Bearer wrong" }))).status, 401);
  assert.equal((await post(port, INIT, as("github:42", { Origin: "https://untrusted.invalid" }))).status, 403);
  assert.equal((await post(port, INIT, as("github:0"))).status, 400);
  assert.equal(mcp.seen.length, 0);
});

test("each user's hour is capped, and anything but JSON or an event stream is a 502", async t => {
  let clock = 1_000_000;
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp, { mcpPerHour: 2 }, { now: () => clock });
  assert.equal((await post(port, INIT, as("github:42"))).status, 200);
  assert.equal((await post(port, INIT, as("github:42"))).status, 200);
  assert.equal((await post(port, INIT, as("github:42"))).status, 429);
  assert.equal((await post(port, INIT, as("github:7"))).status, 200);
  clock += 3_600_001;
  assert.equal((await post(port, INIT, as("github:42"))).status, 200);
  const html = await fakeMcp(t, (_, res) => { res.writeHead(200, { "Content-Type": "text/html" }); res.end("<p>"); });
  assert.equal((await post(await door(t, html), INIT, as("github:42"))).status, 502);
  const error = await fakeMcp(t, (_, res) => { res.writeHead(500, { "Content-Type": "application/json" }); res.end("{}"); });
  assert.equal((await post(await door(t, error), INIT, as("github:42"))).status, 502);
});

test("the deploy gate passes with MCP on, and never dials it", async t => {
  const mcp = await fakeMcp(t);
  const config = { ...validateConfig({ origin: ORIGIN, mcp: true }, secrets), mcpUpstream: mcp.origin };
  const server = createGateway(config, { requestJson: async () => ({}) });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  await verify(config, `http://127.0.0.1:${server.address().port}`);
  assert.equal(mcp.seen.length, 0);
});

test("the upstream check needs openbq-mcp to open a session", async t => {
  await checkMcp({ mcpUpstream: (await fakeMcp(t)).origin });
  const none = await fakeMcp(t, (_, res) => { res.writeHead(200, { "Content-Type": "application/json" }); res.end("{}"); });
  await assert.rejects(checkMcp({ mcpUpstream: none.origin }), /MCP preflight failed/);
});

test("parallel messages from one user are each charged to the hour", async t => {
  const mcp = await fakeMcp(t);
  const port = await door(t, mcp, { mcpPerHour: 3, maxConcurrent: 8 });
  const statuses = (await Promise.all(Array.from({ length: 6 }, () => post(port, INIT, as("github:42"))))).map(r => r.status);
  assert.equal(statuses.filter(s => s === 200).length, 3, JSON.stringify(statuses));
  assert.equal(statuses.filter(s => s === 429).length, 3, JSON.stringify(statuses));
});
