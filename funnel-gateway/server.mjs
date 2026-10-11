// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// openbq-docker v8.0.0. Ported from bdobb-dev/openbb-docker v8.0.3 (775354f)
// funnel-gateway/server.mjs with the /ai (Rita) family and its SOCKS5 dialer removed.

import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import { upstreamPath, newsSubscription, socketTarget, socketTicketNonce, stateFile } from "./policy.mjs";

const MAX_BODY = 2 * 1024 * 1024;
const MAX_SOCKET = 65536;
const digest = value => createHash("sha256").update(value).digest();
function authorized(req, config) {
  const values = req.rawHeaders.filter((_, i) => i % 2 === 0 && req.rawHeaders[i].toLowerCase() === "authorization");
  return values.length === 1 && typeof req.headers.authorization === "string" &&
    timingSafeEqual(digest(req.headers.authorization), digest(`Bearer ${config.token}`));
}
function requestUrl(req, config) {
  if (req.headers.host !== new URL(config.origin).host || !req.url?.startsWith("/") ||
      req.url.startsWith("//") || /[%\\#]/.test(req.url.split("?")[0]) || req.url.includes("#")) return null;
  const url = new URL(req.url, config.origin);
  return url.pathname === req.url.split("?")[0] && url.origin === config.origin ? url : null;
}
function reply(res, code, value = { error: "Request refused" }) {
  res.writeHead(code, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
  });
  res.end(JSON.stringify(value));
}
function reject(socket, code) {
  socket.end(`HTTP/1.1 ${code} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}
// A tailnet upstream: dial the pinned tailnet address directly, but keep the real hostname
// for SNI and certificate validation.
function pinned(origin, address) {
  const hostname = new URL(origin).hostname;
  return {
    servername: hostname,
    rejectUnauthorized: true,
    lookup: (name, options, callback) => {
      if (name !== hostname) return callback(new Error("Unexpected DNS lookup"));
      callback(null, ...(options?.all ? [[{ address, family: 4 }]] : [address, 4]));
    },
  };
}
// The wire: rss-ticker on the tailnet -- the pinned tailnet address, the real hostname kept
// for SNI and the certificate. No credential: the
// pool has none, and reachability is its whole access control (see docker-compose.yml), so
// what protects it is that only this door can reach it and only the approved feeds get
const rssOptions = config => pinned(config.rssOrigin, config.rssAddress);
// Two upstreams at this tag (openbq-docker serves no /ai). /api/... -> openbq-api, plain HTTP
// on the bridge, behind the stack's Basic pair; the prefix is stripped ("/api/api/v1/x" ->
// "/api/v1/x") and the credential injected. /news/... -> rss-ticker, on the tailnet, no
// credential (it has none). Nothing the caller sent goes with either of them.
function target(path, config) {
  if (path.startsWith("/api/")) {
    return { url: new URL(path.slice(4), config.apiOrigin), options: {},
      headers: { Authorization: config.apiAuthorization, Accept: "application/json" } };
  }
  return { url: new URL(path.slice(5), config.rssOrigin), options: rssOptions(config),
    headers: { Accept: "application/json" } };
}

/**
 * The wire's socket. One connection per admitted client, opened only once that client's
 * single subscription frame has passed newsSubscription -- so an invalid or missing frame
 * never opens anything upstream at all. `maxPayload` caps what the pool can push at the
 * same MAX_SOCKET the client side is held to, compression is off (a compressed frame's
 * expanded size is not what maxPayload measures), and a redirect is never followed.
 */
export function connectNews(config) {
  const url = new URL("/ws/news", config.rssOrigin); url.protocol = "wss:";
  return new WebSocket(url, {
    ...rssOptions(config), headers: { Origin: config.rssOrigin },
    handshakeTimeout: 10000, followRedirects: false,
    maxPayload: MAX_SOCKET, perMessageDeflate: false,
  });
}

/** Bounded JSON-only request; never relay cookies, errors, redirects or credentials. */
export async function getJson(path, config, signal) {
  const { url, headers, options } = target(path, config);
  const send = url.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, rejectPromise) => {
    const request = send(url, { ...options, method: "GET", headers, signal }, response => {
      if (response.statusCode !== 200 ||
          !/^application\/json(?:\s*;|$)/i.test(response.headers["content-type"] ?? "")) {
        response.destroy(); return rejectPromise(new Error("Invalid upstream response"));
      }
      let size = 0; const parts = [];
      response.on("data", chunk => {
        size += chunk.length;
        if (size > MAX_BODY) { response.destroy(); rejectPromise(new Error("Body limit")); }
        else parts.push(chunk);
      });
      response.on("error", rejectPromise);
      response.on("end", () => {
        try { resolve(JSON.parse(Buffer.concat(parts).toString("utf8"))); }
        catch { rejectPromise(new Error("Invalid JSON")); }
      });
    });
    request.once("error", rejectPromise);
    request.end();
  });
}

/**
 * Per-user state: the web preview's saved configuration (user ruling 2026-09-20: on
 * the NAS, behind this gateway). The one place a method other than GET is taken.
 * The web layer supplies the id -- the GitHub
 * numeric id its session verified -- under the same machine token as every other
 * request; this side holds the shape:
 * digits for the user, an allow-listed file name (policy.mjs stateFile), JSON only,
 * 256 KiB a file, 2 MiB and 200 files a user. One flat directory per user; a name is
 * stored percent-encoded, so no request can name a path.
 */
const STATE_FILE_MAX = 262144, STATE_USER_MAX = 2 * 1024 * 1024, STATE_USER_FILES = 200;
async function stateFiles(dir) {
  let names; try { names = await readdir(dir); } catch { return []; }
  // A crash between the temp write and its rename leaves a .tmp- behind that no listing
  // or quota counts. Swept once stale; a minute is far past any write still in flight.
  for (const stored of names.filter(n => n.startsWith(".tmp-"))) {
    const temp = join(dir, stored);
    try { if (Date.now() - (await stat(temp)).mtimeMs > 60000) await rm(temp, { force: true }); } catch { /* raced a rename */ }
  }
  // A hand-copied file whose name is not valid percent-encoding must not take the whole
  // user listing down with it: it is skipped, exactly like a name the allow-list refuses.
  return names.map(stored => {
    try { return { stored, name: decodeURIComponent(stored) }; } catch { return null; }
  }).filter(f => f && stateFile(f.name));
}
/** A bounded JSON request body, or the status that refuses it. Parsed only to prove it parses. */
async function jsonBody(req, max) {
  if (!req.headers["content-type"]?.startsWith("application/json")) return 415;
  const length = Number(req.headers["content-length"]);
  if (req.headers["transfer-encoding"] || !Number.isInteger(length)) return 411;
  // Refused on the declared size; the rest of the request is drained, not buffered.
  if (length > max) { req.resume(); return 413; }
  const parts = []; let size = 0;
  for await (const part of req) { size += part.length; if (size > max) return 413; parts.push(part); }
  const body = Buffer.concat(parts);
  try { JSON.parse(body.toString("utf8")); } catch { return 400; }
  return body;
}
async function handleState(req, res, url, config) {
  const match = /^\/state\/(\d{1,20})(?:\/(.+))?$/.exec(url.pathname);
  if (!config.stateDir || !match || url.search) return reply(res, 404);
  const dir = join(config.stateDir, match[1]), name = match[2];
  if (name === undefined) {
    if (req.method !== "GET") return reply(res, 405);
    const files = {};
    for (const f of await stateFiles(dir)) files[f.name] = await readFile(join(dir, f.stored), "utf8");
    return reply(res, 200, { files });
  }
  if (!stateFile(name)) return reply(res, 404);
  const path = join(dir, encodeURIComponent(name));
  if (req.method === "DELETE") { await rm(path, { force: true }); return reply(res, 204); }
  if (req.method !== "PUT") return reply(res, 405);
  const body = await jsonBody(req, STATE_FILE_MAX);
  if (typeof body === "number") return reply(res, body);
  const others = (await stateFiles(dir)).filter(f => f.name !== name);
  let total = body.length;
  for (const f of others) total += (await stat(join(dir, f.stored))).size;
  if (total > STATE_USER_MAX || others.length >= STATE_USER_FILES) return reply(res, 413);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  // Same directory, so the rename is atomic; the name can never pass stateFile.
  const temp = join(dir, ".tmp-" + randomBytes(8).toString("hex"));
  try { await writeFile(temp, body, { mode: 0o600 }); await rename(temp, path); }
  catch (error) { await rm(temp, { force: true }); throw error; }
  return reply(res, 204);
}

/** Test dependency injection is not exposed through environment variables. */
export function createGateway(config, { requestJson = getJson, openNews = connectNews,
  now = Date.now, socketMs = 240000, firstFrameMs = 10000 } = {}) {
  let budget = config.requestsPerMinute, resetAt = now() + 60000, quoteCount = 0, day = Math.floor(now() / 86400000);
  let inflight = 0, sockets = 0;
  // Ticket nonces already admitted, until each ticket's own expiry: single use.
  const admitted = new Map();
  function spend(cost) {
    if (now() >= resetAt) { budget = config.requestsPerMinute; resetAt = now() + 60000; }
    if (budget < cost) return false;
    budget -= cost; return true;
  }
  function quoteAllowed() {
    const currentDay = Math.floor(now() / 86400000);
    if (day !== currentDay) { day = currentDay; quoteCount = 0; }
    if (quoteCount >= config.quoteDailyLimit) return false;
    quoteCount++; return true;
  }
  const wss = new WebSocketServer({ noServer: true, maxPayload: MAX_SOCKET, perMessageDeflate: false });
  const server = createServer({ maxHeaderSize: 16384, requestTimeout: 15000, headersTimeout: 10000,
    keepAliveTimeout: 5000 }, async (req, res) => {
    try {
      // The lock precedes route discovery, health, Host and Origin validation.
      if (!authorized(req, config)) return reply(res, 401);
      const url = requestUrl(req, config);
      if (!url) return reply(res, 421);
      if (req.headers.origin && req.headers.origin !== config.origin) return reply(res, 403);
      if (url.pathname.startsWith("/state/")) {
        if (!spend(1)) return reply(res, 429);
        return await handleState(req, res, url, config);
      }
      if (req.method !== "GET" || req.headers["transfer-encoding"] ||
          (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
      if (!spend(1)) return reply(res, 429);
      if (url.pathname === "/_gateway/health" && !url.search) return reply(res, 200, { ok: true });
      const path = upstreamPath(url, config);
      if (!path) return reply(res, 404);
      // The daily budget is a cap on VENDOR calls. The two manifests under /api/ are
      // openbq-api's own static documents -- no provider is called -- so they are not metered.
      if (inflight >= config.maxConcurrent || (path.startsWith("/api/api/v1/") && !quoteAllowed())) return reply(res, 429);
      inflight++;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      const disconnect = () => { if (!res.writableEnded) controller.abort(); };
      res.once("close", disconnect);
      try { reply(res, 200, await requestJson(path, config, controller.signal)); }
      finally { clearTimeout(timer); res.off("close", disconnect); inflight--; }
    } catch { if (!res.headersSent) reply(res, 502); else res.destroy(); }
  });
  server.maxConnections = 64;
  server.on("clientError", (_, socket) => socket.destroy());
  server.on("upgrade", (req, socket, head) => {
    socket.on("error", () => {});
    socket.setTimeout(10000, () => socket.destroy());
    let url = requestUrl(req, config);
    const tickets = url?.searchParams.getAll("ticket") ?? [];
    if (tickets.length && !req.headers.authorization) {
      // The browser's own socket. Relaying it through a Vercel Function bills function time while it is open, and a browser
      // cannot carry the machine token, so the web layer -- which checked the GitHub
      // session -- signs a thirty-second ticket over the exact target and appends it
      // LAST (policy.mjs socketTicket). What precedes it is what was signed, and
      // is all the route checks below ever see. Off until previewOrigin is set.
      if (!config.previewOrigin) return reject(socket, 401);
      if (req.headers.origin !== config.previewOrigin) return reject(socket, 403);
      const cut = req.url.search(/[?&]ticket=/);
      const target = req.url.slice(0, cut);
      // cut < 0: the parser found a ticket the wire does not spell literally (tick%65t=).
      // What was signed is the literal text, so that is refused here, not by luck below.
      const nonce = cut >= 0 && tickets.length === 1 && req.url.slice(cut + 8) === tickets[0]
        ? socketTicketNonce(config.token, target, tickets[0], now()) : null;
      for (const [used, until] of admitted) if (until <= now()) admitted.delete(used);
      if (!nonce || admitted.has(nonce)) return reject(socket, 401);
      admitted.set(nonce, Number(tickets[0].split(".")[0]));
      // From here the route rules see the SIGNED target, not the wire URL with the ticket
      // still on it -- otherwise every ticketed upgrade would fail the no-query rule below.
      url = new URL(target, config.origin);
    } else {
      if (!authorized(req, config)) return reject(socket, 401);
      if (!url || req.headers.origin !== config.origin) return reject(socket, 403);
    }
    // One socket route at this tag: the wire. policy.mjs' socketTarget holds the rule -- the
    // exact path, no query (the whole subscription is the first frame, not the URL) -- and is
    // the SAME function the web layer's ticket signer consults, so the two can never drift
    // about what may be opened. A subprotocol is refused here: the wire speaks none, and ws
    // would otherwise have to negotiate one. Anything unmatched is 404, before the wire is
    // consulted at all.
    if (req.method !== "GET" || !socketTarget(url.pathname + url.search, config.origin) ||
        req.headers["sec-websocket-protocol"]) return reject(socket, 404);
    // Nothing to subscribe to: the operator has approved no feeds, so there is no socket to
    // open. 503, not 404 -- the route exists, the upstream is simply not configured, which
    // is what verify.mjs's own probe distinguishes.
    if (!Object.keys(config.feeds).length) return reject(socket, 503);
    // Both caps are charged BEFORE handleUpgrade: a refusal must cost the same whether the
    // handshake would have succeeded or not, and an upgrade that is going to be refused must
    // never get as far as allocating a ws client. Six units, a socket's price, since a socket
    // occupies the door for as long as it is open.
    if (sockets >= config.maxSockets || !spend(6)) return reject(socket, 429);
    wss.handleUpgrade(req, socket, head, client => {
      sockets++;
      // The 10s handshake deadline set above must not go on applying to an open socket.
      socket.setTimeout(0);
      let upstream, subscribed = false;
      const close = () => { client.terminate(); upstream?.terminate(); };
      // Two deadlines: an absolute lifetime (a socket is not a lease on the door), and a
      // shorter one for the first frame -- a client that opens and says nothing is holding
      // a slot for free.
      const lifetime = setTimeout(close, socketMs);
      const initial = setTimeout(close, firstFrameMs);
      client.once("close", () => {
        sockets--; clearTimeout(lifetime); clearTimeout(initial); upstream?.terminate();
      });
      client.on("error", close);
      client.on("message", (data, binary) => {
        // One subscription frame, ever: the wire's protocol needs no second one, so a
        // second frame is a client doing something the contract does not describe.
        if (binary || subscribed) return close();
        const frame = newsSubscription(data, config);
        if (!frame) return close();
        subscribed = true; clearTimeout(initial);
        // Connect upstream ONLY on the first validated frame: an invalid or missing
        // subscription must never open an upstream connection at all.
        try { upstream = openNews(config); } catch { return close(); }
        upstream.on("message", (message, isBinary) => {
          if (isBinary || message.length > MAX_SOCKET || client.readyState !== WebSocket.OPEN ||
              client.bufferedAmount > 262144) return close();
          client.send(message, { binary: false });
        });
        upstream.on("error", close);
        upstream.once("close", close);
        if (upstream.readyState === WebSocket.OPEN) return upstream.send(frame);
        upstream.once("open", () => {
          if (client.readyState === WebSocket.OPEN) upstream.send(frame);
        });
      });
    });
  });
  server.closeGateway = () => {
    for (const client of wss.clients) client.terminate();
    server.closeAllConnections();
    return new Promise(resolve => server.close(resolve));
  };
  return server;
}
