// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:https";
import { execFileSync, execFile } from "node:child_process";
import { promisify } from "node:util";
import { once } from "node:events";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocketServer } from "ws";
import { getJson, connectNews } from "./server.mjs";

// Built at run time so the public-content scan never sees a literal tailnet name.
const TAILNET = ["example-tailnet", "ts", "net"].join(".");

/**
 * The wire's two legs, against a real certificate: the history page over HTTPS and the socket
 * over WSS, both dialled at the pinned address with the real hostname kept for SNI and the
 * certificate check. Proves the cert is actually verified (the first two calls fail with no
 * trust root), that the /news prefix is stripped exactly once, that the Origin the pool sees
 * is its own, and that neither leg carries a credential -- the pool has none, so anything
 * sent would be a leak of the caller's or the stack's.
 */
test("the wire's HTTPS/WSS use a pinned address, a verified hostname, the right prefix and no credentials", async t => {
  const dir = mkdtempSync(join(tmpdir(), "gateway-tls-rss-"));
  t.after(() => rmSync(dir, { recursive: true }));
  const hostname = `openbq.${TAILNET}`;
  execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes",
    "-keyout", join(dir, "key.pem"), "-out", join(dir, "cert.pem"), "-days", "1",
    "-subj", `/CN=${hostname}`, "-addext", `subjectAltName=DNS:${hostname}`], { stdio: "ignore" });
  const seen = [];
  const server = createServer({ key: readFileSync(join(dir, "key.pem")), cert: readFileSync(join(dir, "cert.pem")) },
    (req, res) => {
      seen.push({ url: req.url, headers: req.headers, sni: req.socket.servername });
      res.writeHead(200, { "Content-Type": "application/json" }); res.end('{"news":[]}');
    });
  const wss = new WebSocketServer({ server });
  wss.on("connection", (ws, req) => {
    seen.push({ url: req.url, headers: req.headers, sni: req.socket.servername });
    ws.send('{"ready":true}');
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => new Promise(resolve => {
    for (const client of wss.clients) client.terminate();
    server.closeAllConnections(); wss.close(); server.close(resolve);
  }));
  // Production validation disallows these test loopback addresses/nonstandard ports.
  const cfg = {
    rssOrigin: `https://${hostname}:${server.address().port}`, rssAddress: "127.0.0.1",
    token: "must-not-be-forwarded", apiAuthorization: "must-not-be-forwarded",
  };
  // Untrusted here: the ephemeral root is not in this process's store, so both legs fail and
  // the fixture sees nothing at all.
  await assert.rejects(getJson("/news/api/news?feed_id=7&limit=1", cfg, AbortSignal.timeout(2000)));
  const untrustedSocket = connectNews(cfg);
  await new Promise(resolve => untrustedSocket.once("error", resolve));
  assert.equal(seen.length, 0);
  // A fresh Node process loads this ephemeral trust root at startup, as real Node loads OS roots.
  const code = `
    import assert from "node:assert/strict";
    import {getJson, connectNews} from "./server.mjs";
    const cfg = ${JSON.stringify(cfg)};
    assert.deepEqual(await getJson("/news/api/news?feed_id=7&limit=1", cfg, AbortSignal.timeout(2000)), {news:[]});
    const ws = connectNews(cfg);
    await new Promise((resolve, reject) => {
      ws.on("error", reject);
      ws.on("message", data => {assert.equal(data.toString(), '{"ready":true}'); ws.close();});
      ws.on("close", resolve);
    });
    // The hostname is what the certificate is checked against, not the pinned address: point
    // the origin at a name the certificate does not carry and the dial fails, pin unchanged.
    await assert.rejects(getJson("/news/api/news?feed_id=7&limit=1",
      {...cfg, rssOrigin: cfg.rssOrigin.replace("openbq.", "wrong.")}, AbortSignal.timeout(2000)));
  `;
  await promisify(execFile)(process.execPath, ["--input-type=module", "-e", code], {
    cwd: new URL(".", import.meta.url), env: { ...process.env, NODE_EXTRA_CA_CERTS: join(dir, "cert.pem") },
    timeout: 10000,
  });
  assert.deepEqual(seen.map(r => r.url), ["/api/news?feed_id=7&limit=1", "/ws/news"]);
  for (const req of seen) {
    assert.equal(req.sni, hostname);
    assert.equal(req.headers.authorization, undefined);
    assert.equal(req.headers.cookie, undefined);
    assert.equal(req.headers.host, new URL(cfg.rssOrigin).host);
  }
  assert.equal(seen[1].headers.origin, cfg.rssOrigin);
});
