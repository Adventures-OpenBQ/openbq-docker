// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { request } from "node:http";
import { once } from "node:events";
import { createGateway } from "./server.mjs";
import { validateConfig } from "./config.mjs";

test("a late watchlist POST cannot borrow an already occupied request slot", async t => {
  const origin = `https://openbq.${["example-tailnet", "ts", "net"].join(".")}:10000`;
  const token = "synthetic_test_credential_not_for_deployment";
  const cfg = validateConfig({ origin, maxConcurrent: 1, liveGrid: true },
    { token, apiUsername: "test", apiPassword: "test" });
  let release, reached;
  const occupied = new Promise(resolve => { reached = resolve; });
  const held = new Promise(resolve => { release = resolve; });
  let watchlistCalls = 0;
  const server = createGateway(cfg, {
    requestJson: async () => { reached(); await held; return []; },
    sendSubscription: async () => { watchlistCalls++; return { status: 201, json: {} }; },
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(async () => { release(); await server.closeGateway(); });
  const body = '{"symbol":"AAPL"}';
  const start = (path, method) => {
    let req;
    const done = new Promise((resolve, reject) => {
      req = request({ host: "127.0.0.1", port: server.address().port, path, method,
        headers: { Host: new URL(origin).host, Authorization: `Bearer ${token}`,
          ...(method === "POST" ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } : {}) } },
      res => { res.resume(); res.once("end", () => resolve(res.statusCode)); });
      req.once("error", reject);
    });
    return { req, done };
  };
  const receiving = once(server, "request");
  const late = start("/grid/api/subscriptions", "POST");
  late.req.flushHeaders(); await receiving;
  const first = start("/grid/live_grid?symbol=AAPL", "GET");
  first.req.end(); await occupied;
  late.req.end(body);
  assert.equal(await late.done, 429);
  assert.equal(watchlistCalls, 0);
  release(); assert.equal(await first.done, 200);
});
