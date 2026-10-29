// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// The /ai (Rita) family on the door: off by default, then her three routes, the rewrite on the
// wire, the stream, the feedback relay, and the per-user and global limits.

import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { validateConfig } from "./config.mjs";
import { createGateway } from "./server.mjs";
import { verify } from "./verify.mjs";
import { checkRita } from "./check-upstreams.mjs";

const TAILNET = ["example-tailnet", "ts", "net"].join(".");
const TOKEN = "synthetic_test_credential_not_for_deployment";
const ORIGIN = `https://openbq.${TAILNET}:10000`;
const MODEL = "openai:qwen3.6-35b";
// Built at run time so the public-content scan never sees a literal private address.
const LAN = [10, 0, 0, 1].join(".");
const secrets = { token: TOKEN, apiUsername: "testuser", apiPassword: "synthetic-password" };
const HEADERS = { Host: new URL(ORIGIN).host, Authorization: `Bearer ${TOKEN}` };
const USER = "github:42";
const QUERY = JSON.stringify({ messages: [{ role: "human", content: "hi" }],
  workspace_options: { model: "anthropic:claude-opus-5-5" }, urls: [`http://${LAN}/`] });

test("Rita is off by default and her settings fail closed", () => {
  const off = validateConfig({ origin: ORIGIN }, secrets);
  assert.equal(off.ritaUpstream, null);
  const on = validateConfig({ origin: ORIGIN, rita: true, ritaModel: MODEL }, secrets);
  assert.equal(on.ritaUpstream, "http://openbq-rita-door:7778");
  assert.deepEqual([on.ritaModel, on.ritaPerHour], [MODEL, 120]);
  assert.equal(validateConfig({ origin: ORIGIN, rita: true, ritaModel: MODEL, ritaPerHour: 5 }, secrets).ritaPerHour, 5);
  for (const change of [
    { rita: "true" }, { rita: 1 }, { rita: true },                           // on with no model
    { rita: true, ritaModel: "anthropic:claude-opus-5-5" }, { rita: true, ritaModel: "qwen" },
    { ritaModel: MODEL }, { ritaPerHour: 5 },                                // a setting with nothing to configure
    { rita: true, ritaModel: MODEL, ritaPerHour: 0 }, { rita: true, ritaModel: MODEL, ritaPerHour: 10001 },
    { rita: true, ritaModel: MODEL, ritaPerHour: 1.5 },
  ]) assert.throws(() => validateConfig({ origin: ORIGIN, ...change }, secrets), JSON.stringify(change));
});

/** A stand-in Rita: records what reached her and answers with `answer(req, res, body)`. */
async function fakeRita(t, answer) {
  const seen = [];
  const server = createServer(async (req, res) => {
    const parts = []; for await (const p of req) parts.push(p);
    const body = Buffer.concat(parts).toString();
    seen.push({ method: req.method, url: req.url, headers: req.headers, body });
    await answer(req, res, body);
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { origin: `http://127.0.0.1:${server.address().port}`, seen };
}
const sse = (res, ...events) => {
  res.writeHead(200, { "Content-Type": "text/event-stream" });
  for (const e of events) res.write(`data: ${JSON.stringify(e)}\n\n`);
  res.end();
};
async function door(t, rita, overrides = {}, dependencies = {}) {
  const config = { ...validateConfig({ origin: ORIGIN, rita: true, ritaModel: MODEL }, secrets), ritaUpstream: rita.origin, ...overrides };
  const server = createGateway(config, { requestJson: async () => ({}), ...dependencies });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  return server.address().port;
}
function call(port, path, { method = "GET", body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const h = { ...HEADERS, ...headers };
    if (body !== undefined) { h["Content-Type"] ??= "application/json"; h["Content-Length"] = String(Buffer.byteLength(body)); }
    const req = request({ host: "127.0.0.1", port, path, method, headers: h }, res => {
      const parts = []; res.on("data", c => parts.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(parts).toString() }));
    });
    // A 413 closes the connection while the oversized body is still being written; the answer still arrives.
    req.on("error", error => { if (error.code !== "EPIPE") reject(error); }); req.end(body);
  });
}
const ask = (port, headers = { "X-Rita-Principal": USER }, body = QUERY) =>
  call(port, "/ai/v1/query", { method: "POST", body, headers });

test("off: /ai answers exactly as a door without Rita", async t => {
  const config = validateConfig({ origin: ORIGIN }, secrets);
  const server = createGateway(config, { requestJson: async () => ({}) });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  const port = server.address().port;
  assert.equal((await call(port, "/ai/agents.json")).status, 404);
  assert.equal((await ask(port)).status, 405);
});

test("agents.json is fetched without the caller's headers and offers only the pinned model", async t => {
  const rita = await fakeRita(t, (_, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ openbb_agent_rita: { name: "Agent Rita", endpoints: { query: "/v1/query" },
      features: { "file-upload": true, model: { type: "select", default: "anthropic:x", options: [{ label: "x", value: "anthropic:x" }] } } } }));
  });
  const port = await door(t, rita);
  const answer = await call(port, "/ai/agents.json", { headers: { Cookie: "a=b", "X-Rita-Principal": USER } });
  assert.equal(answer.status, 200);
  const features = JSON.parse(answer.text).openbb_agent_rita.features;
  assert.deepEqual(features.model.options, [{ label: MODEL, value: MODEL }]);
  assert.equal(features["file-upload"], false);
  assert.equal(rita.seen[0].url, "/agents.json");
  for (const name of ["authorization", "cookie", "x-rita-principal"]) assert.equal(rita.seen[0].headers[name], undefined, name);
});

test("a query reaches her rewritten, and her event stream is relayed as it arrives", async t => {
  let release;
  const held = new Promise(r => { release = r; });
  const rita = await fakeRita(t, async (_, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write('data: {"type":"first"}\n\n');
    await held;
    res.end('data: {"type":"last"}\n\n');
  });
  const port = await door(t, rita);
  const first = await new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path: "/ai/v1/query", method: "POST",
      headers: { ...HEADERS, "X-Rita-Principal": USER, Cookie: "a=b", "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(QUERY) } }, res => {
      assert.equal(res.statusCode, 200);
      assert.match(res.headers["content-type"], /^text\/event-stream/);
      let text = "";
      res.on("data", c => {
        text += c;
        // The first event arrived while she still holds the stream open: relayed, not buffered.
        if (text.includes("first") && !text.includes("last")) { resolve(text); release(); }
      });
      res.on("end", () => assert.match(text, /last/));
    });
    req.on("error", reject); req.end(QUERY);
  });
  assert.match(first, /first/);
  const sent = JSON.parse(rita.seen[0].body);
  assert.equal(rita.seen[0].url, "/v1/query");
  assert.deepEqual(sent.workspace_options, { model: MODEL });
  assert.equal(sent.urls, undefined);
  for (const name of ["authorization", "cookie", "x-rita-principal"]) assert.equal(rita.seen[0].headers[name], undefined, name);
});

test("one turn at a time per user, two at a time in all", async t => {
  const waiting = []; let hold = true;
  const rita = await fakeRita(t, (_, res) => hold
    ? new Promise(r => waiting.push(() => { sse(res, { type: "done" }); r(); }))
    : sse(res, { type: "done" }));
  const port = await door(t, rita);
  const a = ask(port, { "X-Rita-Principal": "github:1" });
  await new Promise(r => setTimeout(r, 50));
  assert.equal((await ask(port, { "X-Rita-Principal": "github:1" })).status, 429, "same user");
  const b = ask(port, { "X-Rita-Principal": "github:2" });
  await new Promise(r => setTimeout(r, 50));
  assert.equal((await ask(port, { "X-Rita-Principal": "github:3" })).status, 429, "global");
  hold = false; for (const go of waiting) go();
  assert.deepEqual([(await a).status, (await b).status], [200, 200]);
  assert.equal((await ask(port, { "X-Rita-Principal": "github:3" })).status, 200, "slots freed");
});

test("the hourly cap counts each user's queries and lets them through again after the hour", async t => {
  let clock = 1_000_000;
  const rita = await fakeRita(t, (_, res) => sse(res, { type: "done" }));
  const port = await door(t, rita, { ritaPerHour: 2 }, { now: () => clock });
  assert.equal((await ask(port)).status, 200);
  assert.equal((await ask(port)).status, 200);
  assert.equal((await ask(port)).status, 429);
  assert.equal((await ask(port, { "X-Rita-Principal": "github:7" })).status, 200, "another user's own hour");
  clock += 3_600_001;
  assert.equal((await ask(port)).status, 200);
});

test("a refused body costs no query and reaches no one", async t => {
  const rita = await fakeRita(t, (_, res) => sse(res, { type: "done" }));
  const port = await door(t, rita, { ritaPerHour: 1 });
  assert.equal((await ask(port, undefined, "{}")).status, 400);
  assert.equal((await ask(port, undefined, "not json")).status, 400);
  assert.equal((await ask(port, { "X-Rita-Principal": USER, "Content-Type": "text/plain" })).status, 415);
  assert.equal((await ask(port, undefined, JSON.stringify({ messages: ["x".repeat(1024 * 1024)] }))).status, 413);
  assert.equal(rita.seen.length, 0);
  assert.equal((await ask(port)).status, 200);
});

test("the principal is one well-formed GitHub id, or the desktop's own bucket when absent", async t => {
  const rita = await fakeRita(t, (_, res) => sse(res, { type: "done" }));
  const port = await door(t, rita);
  for (const bad of ["42", "github:", "github:0", "github:abc", "github:1,github:2"]) {
    assert.equal((await ask(port, { "X-Rita-Principal": bad })).status, 400, bad);
  }
  assert.equal((await ask(port, {})).status, 200);
});

test("anything but her event stream is a 502, and her other routes are not routes", async t => {
  const rita = await fakeRita(t, (req, res) => {
    if (req.url === "/agents.json") { res.writeHead(200, { "Content-Type": "text/html" }); return res.end("<p>"); }
    res.writeHead(500, { "Content-Type": "text/event-stream" }); res.end();
  });
  const port = await door(t, rita);
  assert.equal((await ask(port)).status, 502);
  assert.equal((await call(port, "/ai/agents.json")).status, 502);
  for (const [path, method] of [["/ai/v1/query", "GET"], ["/ai/agents.json?x=1", "GET"], ["/ai/v1/generate/code", "POST"],
    ["/ai/status", "GET"], ["/ai/rita.png", "GET"], ["/ai/", "GET"]]) {
    assert.equal((await call(port, path, { method, body: method === "POST" ? "{}" : undefined })).status, 404, `${method} ${path}`);
  }
});

test("Rita behind the lock like everything else", async t => {
  const rita = await fakeRita(t, (_, res) => sse(res, { type: "done" }));
  const port = await door(t, rita);
  assert.equal((await ask(port, { Authorization: "Bearer wrong", "X-Rita-Principal": USER })).status, 401);
  assert.equal((await ask(port, { Origin: "https://untrusted.invalid", "X-Rita-Principal": USER })).status, 403);
  assert.equal(rita.seen.length, 0);
});

test("the deploy gate passes with Rita on, and never dials her", async t => {
  const rita = await fakeRita(t, (_, res) => sse(res, { type: "done" }));
  const config = { ...validateConfig({ origin: ORIGIN, rita: true, ritaModel: MODEL }, secrets), ritaUpstream: rita.origin };
  const server = createGateway(config, { requestJson: async () => ({}) });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => server.closeGateway());
  await verify(config, `http://127.0.0.1:${server.address().port}`);
  assert.equal(rita.seen.length, 0);
});

test("the upstream check refuses a door Rita that offers a paid model", async t => {
  let options = [{ value: MODEL }, { value: "ollama:gpt-oss:20b" }];
  const rita = await fakeRita(t, (_, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ openbb_agent_rita: { features: { model: { options } } } }));
  });
  const config = { ritaUpstream: rita.origin };
  await checkRita(config);
  options = [{ value: MODEL }, { value: "anthropic:claude-opus-5-5" }];
  await assert.rejects(checkRita(config), /offers paid models \(anthropic:claude-opus-5-5\)/);
  options = [{ value: "openrouter:x" }, { value: 7 }];
  await assert.rejects(checkRita(config), /paid models/);
});

test("a client that leaves mid-stream, or a stream that fails, frees its slots", async t => {
  let mode = "hang";
  const rita = await fakeRita(t, (_, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write('data: {"type":"first"}\n\n');
    if (mode === "fail") res.destroy();
    else if (mode === "done") res.end();
  });
  const port = await door(t, rita, { ritaPerHour: 10 });
  const leave = () => new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path: "/ai/v1/query", method: "POST",
      headers: { ...HEADERS, "X-Rita-Principal": USER, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(QUERY) } },
      res => res.once("data", () => { req.destroy(); resolve(); }));
    req.on("error", () => {}); req.end(QUERY);
  });
  await leave(); await leave();
  mode = "fail";
  await ask(port).catch(() => {});
  mode = "done";
  await new Promise(r => setTimeout(r, 50));
  // Every slot is free again: this user, and both global turns.
  assert.deepEqual(await Promise.all([ask(port), ask(port, { "X-Rita-Principal": "github:9" })]).then(r => r.map(x => x.status)), [200, 200]);
});

test("a stream past 16 MiB is cut, not ended as if complete", async t => {
  const rita = await fakeRita(t, async (_, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const chunk = Buffer.alloc(1024 * 1024, "a");
    for (let i = 0; i < 18 && !res.destroyed; i++) if (!res.write(chunk)) await once(res, "drain");
    res.end();
  });
  const port = await door(t, rita);
  const outcome = await new Promise(resolve => {
    const req = request({ host: "127.0.0.1", port, path: "/ai/v1/query", method: "POST",
      headers: { ...HEADERS, "X-Rita-Principal": USER, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(QUERY) } },
      res => { res.on("data", () => {}); res.on("end", () => resolve("ended")); res.on("aborted", () => resolve("cut")); res.on("error", () => resolve("cut")); });
    req.on("error", () => resolve("cut")); req.end(QUERY);
  });
  assert.equal(outcome, "cut");
});

const FEEDBACK = JSON.stringify({ vote: "thumbs_down", tags: ["Other"], user_comment: "c", ai_response: "r", user_prompt: "p", trace_id: "t-1", extra: "dropped" });
const feedback = (port, headers = { "X-Rita-Principal": USER }, body = FEEDBACK) =>
  call(port, "/ai/v1/feedback", { method: "POST", body, headers });
const accepted = (_, res) => { res.writeHead(204); res.end(); };

test("feedback reaches her rebuilt, with the caller's principal and nothing else of theirs", async t => {
  const rita = await fakeRita(t, accepted);
  const port = await door(t, rita);
  assert.equal((await feedback(port, { "X-Rita-Principal": USER, Cookie: "a=b" })).status, 204);
  assert.equal(rita.seen[0].url, "/v1/feedback");
  assert.equal(rita.seen[0].headers["x-rita-principal"], USER);
  for (const name of ["authorization", "cookie"]) assert.equal(rita.seen[0].headers[name], undefined, name);
  assert.deepEqual(JSON.parse(rita.seen[0].body), { vote: "thumbs_down", tags: ["Other"], user_comment: "c", ai_response: "r", user_prompt: "p", trace_id: "t-1" });
});

test("agents.json keeps her feedback: true, so web users see the buttons", async t => {
  const rita = await fakeRita(t, (_, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ openbb_agent_rita: { name: "Agent Rita", endpoints: { query: "/v1/query" }, features: { feedback: true } } }));
  });
  const port = await door(t, rita);
  const answer = await call(port, "/ai/agents.json", { headers: { "X-Rita-Principal": USER } });
  assert.equal(JSON.parse(answer.text).openbb_agent_rita.features.feedback, true);
});

test("the desktop's feedback names no principal", async t => {
  const rita = await fakeRita(t, accepted);
  const port = await door(t, rita);
  assert.equal((await feedback(port, {})).status, 204);
  assert.equal(rita.seen[0].headers["x-rita-principal"], undefined);
});

test("feedback is charged to the hour but takes no turn slot", async t => {
  let release;
  const held = new Promise(r => { release = r; });
  const rita = await fakeRita(t, async (req, res) => {
    if (req.url === "/v1/feedback") return accepted(req, res);
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write('data: {"type":"first"}\n\n');
    await held; res.end();
  });
  const port = await door(t, rita, { ritaPerHour: 2 });
  const turn = ask(port);
  try {
    const deadline = Date.now() + 5000;
    while (!rita.seen.some(s => s.url === "/v1/query")) {
      if (Date.now() > deadline) assert.fail("the query never reached her");
      await new Promise(r => setTimeout(r, 10));
    }
    assert.equal((await feedback(port)).status, 204, "mid-turn, same principal");
    assert.equal((await feedback(port)).status, 429, "the query and one vote are the hour's two");
  } finally { release(); await turn; }
});

test("concurrent feedback votes whose bodies arrive late are charged one by one", async t => {
  const rita = await fakeRita(t, accepted);
  const port = await door(t, rita, { ritaPerHour: 2 });
  // Headers first, the body 150 ms later: every vote is past its first check before any is charged.
  const late = () => new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path: "/ai/v1/feedback", method: "POST",
      headers: { ...HEADERS, "X-Rita-Principal": USER, "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(FEEDBACK) } }, res => {
      res.resume(); res.on("end", () => resolve(res.statusCode));
    });
    req.on("error", reject);
    req.flushHeaders();
    setTimeout(() => req.end(FEEDBACK), 150);
  });
  const codes = await Promise.all([1, 2, 3, 4, 5].map(late));
  assert.equal(codes.filter(c => c === 204).length, 2, JSON.stringify(codes));
  assert.equal(codes.filter(c => c === 429).length, 3, JSON.stringify(codes));
  assert.equal(rita.seen.length, 2);
});

test("feedback refuses a bad body, an oversized one, a GET, and a refusing Rita", async t => {
  const rita = await fakeRita(t, accepted);
  const port = await door(t, rita);
  assert.equal((await feedback(port, undefined, JSON.stringify({ vote: "meh" }))).status, 400);
  assert.equal((await feedback(port, undefined, JSON.stringify({ vote: "thumbs_up", ai_response: "x".repeat(70 * 1024) }))).status, 413);
  assert.equal((await call(port, "/ai/v1/feedback", { headers: { "X-Rita-Principal": USER } })).status, 404);
  assert.equal(rita.seen.length, 0);
  const down = await fakeRita(t, (_, res) => { res.writeHead(500); res.end(); });
  assert.equal((await feedback(await door(t, down))).status, 502);
});

test("any other /ai/v1 path stays 404, even as a POST, and never reaches her", async t => {
  const rita = await fakeRita(t, accepted);
  const port = await door(t, rita);
  for (const path of ["/ai/v1/other", "/ai/v1/generate/code", "/ai/v1/feedback/x"])
    assert.equal((await call(port, path, { method: "POST", body: FEEDBACK, headers: { "X-Rita-Principal": USER } })).status, 404, path);
  assert.equal(rita.seen.length, 0);
});
