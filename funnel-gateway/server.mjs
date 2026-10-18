// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// openbq-docker v8.0.0. Ported from bdobb-dev/openbb-docker v8.0.3 (775354f)
// funnel-gateway/server.mjs with the /ai (Rita) family and its SOCKS5 dialer removed.
// The socket door also serves the reference's /ref/live_grid_ws, which came down to v3/v4
// with the reference backend; at this tag /news/ws/news joins it.

import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import { tableRoute, tableControlRoute, TABLE_CONTROL_CONCURRENCY, TABLE_RESPONSE_BYTES, upstreamPath, newsSubscription, refSubscription, socketTarget, socketTicketNonce, stateFile } from "./policy.mjs";

const MAX_BODY = 2 * 1024 * 1024;
// The root manifests are static catalogue documents, not data: openbq-api's widgets.json is
// 5.0 MB (998 widgets). They get their own cap; every other path keeps MAX_BODY.
const MANIFESTS = new Set(["/api/widgets.json", "/api/apps.json", "/ref/widgets.json", "/ref/apps.json"]);
const MANIFEST_MAX = 16 * 1024 * 1024; // ponytail: manifests are buffered and parsed (~6x their size at peak); 8 concurrent 16 MiB manifests could pass mem_limit 512m — stream them unparsed if that ever matters.
const MAX_SOCKET = 65536;
/**
 * The packaged desktop app's webview origins (V10-P1, user ruling 2026-10-15). Tauri's http
 * plugin stamps one of these on every request it makes (tauri://localhost on macOS, iOS and
 * Linux; http://tauri.localhost on Windows and Android), and the webview's own WebSocket
 * carries the same one. An Origin is never a credential: these pass the Origin rule only
 * behind the Bearer lock, on HTTP -- never on an upgrade. (Its HTTP half moved down with the
 * gateway; the socket ticket for the webview's own socket, /grid/ws_ticket, arrives at v10.)
 * The dev server's http://localhost:1420 is deliberately not one of them.
 */
export const DESKTOP_ORIGINS = new Set(["tauri://localhost", "http://tauri.localhost"]);
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
const COMMON = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
};
const LOGO = "/ref/assets/bdobb-logo.svg", MAX_SVG = 262144;
/** The reference logo's bytes, relayed as SVG. */
class SvgBody { constructor(text) { this.text = text; } }
/** A text/plain answer (the video routes return a bare URL), relayed as text. */
class TextBody { constructor(text) { this.text = text; } }
function reply(res, code, value = { error: "Request refused" }) {
  if (value instanceof SvgBody) {
    // The logo: same common headers, its own type, and a sandbox CSP so a directly opened SVG runs nothing.
    res.writeHead(code, { ...COMMON, "Content-Type": "image/svg+xml",
      "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'" });
    return res.end(value.text);
  }
  if (value instanceof TextBody) {
    res.writeHead(code, { ...COMMON, "Content-Type": "text/plain; charset=utf-8" });
    return res.end(value.text);
  }
  res.writeHead(code, { ...COMMON, "Content-Type": "application/json" });
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
// Three upstreams at this tag (openbq-docker serves no /ai). /api/... -> openbq-api, plain HTTP
// on the bridge, behind the stack's Basic pair; the prefix is stripped ("/api/api/v1/x" ->
// "/api/v1/x") and the credential injected. /news/... -> rss-ticker, on the tailnet, no
// credential (it has none). /ref/... -> the keyless reference fixture, "/ref" stripped, NO
// Authorization header. Nothing the caller sent goes with any of them.
// The upstream URL is built by concatenation, never by resolving the path against the origin,
// so the host can only ever be the fixed origin (a "//host" path would otherwise replace it).
function target(path, config) {
  if (path.startsWith("/api/")) {
    return { url: new URL(config.apiOrigin + path.slice(4)), options: {},
      headers: { Authorization: config.apiAuthorization, Accept: "application/json" } };
  }
  if (path.startsWith("/news/")) {
    return { url: new URL(config.rssOrigin + path.slice(5)), options: rssOptions(config),
      headers: { Accept: "application/json" } };
  }
  return { url: new URL(config.refOrigin + path.slice(4)), options: {},
    headers: { Accept: path === LOGO ? "image/svg+xml" : "application/json" } };
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

/**
 * The reference's socket, opened once a client's first params frame has passed
 * refSubscription -- so a client that opens and says nothing, or says something invalid,
 * never opens anything upstream. ws:// (the reference listens on the bridge, no TLS), no
 * credential (it is keyless), no subprotocol. Built by concatenation on the fixed refOrigin,
 * like target(). Same bounds as any relayed socket: MAX_SOCKET on the push, compression off,
 * no redirect, a 10 s handshake deadline.
 */
export function connectRef(config) {
  return new WebSocket("ws" + config.refOrigin.slice("http".length) + "/live_grid_ws", {
    handshakeTimeout: 10000, followRedirects: false, maxPayload: MAX_SOCKET, perMessageDeflate: false });
}

/** Bounded JSON or text/plain request (plus the one SVG logo); never relay cookies, errors, redirects or credentials. */
export async function getJson(path, config, signal) {
  const { url, headers, options } = target(path, config);
  const send = url.protocol === "https:" ? httpsRequest : httpRequest;
  const svg = path === LOGO, limit = svg ? MAX_SVG : MANIFESTS.has(path) ? MANIFEST_MAX : MAX_BODY;
  return new Promise((resolve, rejectPromise) => {
    const request = send(url, { ...options, method: "GET", headers, signal }, response => {
      const type = response.headers["content-type"] ?? "", plain = !svg && /^text\/plain(?:\s*;|$)/i.test(type);
      if (response.statusCode !== 200 ||
          !(plain || (svg ? /^image\/svg\+xml(?:\s*;|$)/i : /^application\/json(?:\s*;|$)/i).test(type))) {
        response.destroy(); return rejectPromise(new Error("Invalid upstream response"));
      }
      let size = 0; const parts = [];
      response.on("data", chunk => {
        size += chunk.length;
        if (size > limit) { response.destroy(); rejectPromise(new Error("Body limit")); }
        else parts.push(chunk);
      });
      response.on("error", rejectPromise);
      response.on("end", () => {
        const text = Buffer.concat(parts).toString("utf8");
        if (svg) return resolve(new SvgBody(text));
        if (plain) return resolve(new TextBody(text));
        try { resolve(JSON.parse(text)); }
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

// Identity assertions use a separate server-only credential. Possession of the shared
// desktop bearer can never choose a web principal. Duplicate/malformed assertions refuse.
function tablePrincipal(req, config) {
  const count = name => req.rawHeaders.filter((v,i) => i % 2 === 0 && v.toLowerCase() === name).length;
  const relay = req.headers["x-table-relay-token"];
  if (relay !== undefined) {
    if (count("x-table-relay-token") !== 1 || count("x-table-principal") !== 1 ||
        !config.tableRelayToken || !timingSafeEqual(digest(relay), digest(config.tableRelayToken)) ||
        !/^github:[1-9][0-9]{0,19}$/.test(req.headers["x-table-principal"] ?? "")) return null;
    return req.headers["x-table-principal"];
  }
  return config.tableDesktopPrincipal ?? null;
}
async function tableBody(req, route, signal) {
  if (!route.maxBody) {
    if (req.headers["transfer-encoding"] || Number(req.headers["content-length"] ?? 0) !== 0) return 405;
    return undefined;
  }
  if (!route.upload && !/^application\/json(?:;|$)/i.test(req.headers["content-type"] ?? "")) return 415;
  if (Number(req.headers["content-length"]) > route.maxBody) { req.resume(); return 413; }
  const abort = () => req.destroy(); signal.addEventListener("abort", abort, {once:true});
  try {
    const chunks=[]; let size=0;
    for await (const chunk of req.iterator({destroyOnReturn:false})) { size+=chunk.length; if(size>route.maxBody) {req.resume();return 413;} chunks.push(chunk); }
    const body=Buffer.concat(chunks);
    if (!route.upload) { try { JSON.parse(body.toString("utf8")); } catch { return 400; } }
    return body;
  } finally { signal.removeEventListener("abort",abort); }
}
// Buffer each finite export batch before publishing headers: truncated, oversized or
// failed streams cannot masquerade as a successful partial result. No retry on mutation.
async function tableExchange(req, res, route, config) {
  if (route.managed && !config.tableOrigin) return reply(res,503);
  const principal = route.managed ? tablePrincipal(req, config) : null;
  if (route.managed && !principal) return reply(res,401);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),route.managed ? config.tableTimeoutMs : config.ssrmTimeoutMs);
  const disconnect=()=>{if(!res.writableEnded)controller.abort();}; res.once("close",disconnect);
  try {
    const body=await tableBody(req,route,controller.signal);
    if(typeof body === "number"){if(body===413 || !req.complete)res.setHeader("Connection","close");return reply(res,body);}
    const destination=route.managed ? {url:new URL(config.tableOrigin+route.path.slice(6)),headers:{
      "X-Table-Gateway-Token":config.tableGatewayToken,"X-Table-Principal":principal}} : target(route.path,config);
    const headers={...destination.headers,Accept:"application/json"};
    if(body!==undefined) headers["Content-Type"]=route.upload ? (req.headers["content-type"] ?? "application/octet-stream") : "application/json";
    if(route.upload) for(const name of ["idempotency-key","x-upload-filename"]) {
      if(typeof req.headers[name] === "string" && req.headers[name].length<=512) headers[name]=req.headers[name];
    }
    const response=await fetch(destination.url,{method:req.method,headers,body,redirect:"error",signal:controller.signal});
    if(!/^application\/json(?:;|$)/i.test(response.headers.get("content-type")??"")) {await response.body?.cancel();return reply(res,502);}
    const chunks=[]; let size=0;
    for await(const chunk of response.body??[]) {size+=chunk.length;if(size>TABLE_RESPONSE_BYTES){controller.abort();throw new Error("Table response limit");}chunks.push(Buffer.from(chunk));}
    let json;try{json=JSON.parse(Buffer.concat(chunks).toString("utf8"));}catch{return reply(res,502);}
    if(!response.ok) {
      const status=[400,401,404,409,410,413,429,503].includes(response.status)?response.status:502;
      return reply(res,status,{error:{code:"upstream_refused",message:"Table request refused"}});
    }
    // reply() writes its own headers, so od's x-openbq-ssrm cache marker never reaches the client.
    reply(res,response.status,json);
  } finally {clearTimeout(timer);res.off("close",disconnect);}
}

/** Test dependency injection is not exposed through environment variables. */
export function createGateway(config, { requestJson = getJson, openNews = connectNews, openRef = connectRef,
  now = Date.now, pingMs = 30000, firstFrameMs = 10000, requestMs = 12000 } = {}) {
  let inflight = 0, controlInflight = 0, sockets = 0;
  const approvedIds = new Set(Object.values(config.feeds));
  // Ticket nonces already admitted, until each ticket's own expiry: single use.
  const admitted = new Map();
  const wss = new WebSocketServer({ noServer: true, maxPayload: MAX_SOCKET, perMessageDeflate: false });
  const server = createServer({ maxHeaderSize: 16384, requestTimeout: 15000, headersTimeout: 10000,
    keepAliveTimeout: 5000 }, async (req, res) => {
    try {
      // The lock precedes route discovery, health, Host and Origin validation.
      if (!authorized(req, config)) return reply(res, 401);
      const url = requestUrl(req, config);
      if (!url) return reply(res, 421);
      const origin = req.headers.origin;
      if (origin && origin !== config.origin && !DESKTOP_ORIGINS.has(origin)) return reply(res, 403);
      if (url.pathname.startsWith("/state/")) {
        return await handleState(req, res, url, config);
      }
      const table = tableRoute(url, req.method, config);
      if (table || url.pathname.startsWith("/table/")) {
        if (!table) return reply(res,404);
        const control = tableControlRoute(table, req.method);
        if (control ? controlInflight >= TABLE_CONTROL_CONCURRENCY : inflight >= config.maxConcurrent) return reply(res,429);
        if (control) controlInflight++; else inflight++;
        try { return await tableExchange(req,res,table,config); }
        finally { if (control) controlInflight--; else inflight--; }
      }
      if (req.method !== "GET" || req.headers["transfer-encoding"] ||
          (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
      if (url.pathname === "/_gateway/health" && !url.search) return reply(res, 200, { ok: true });
      const path = upstreamPath(url, config);
      if (!path) return reply(res, 404);
      if (inflight >= config.maxConcurrent) return reply(res, 429);
      inflight++;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), requestMs);
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
    const url = requestUrl(req, config);
    const tickets = url?.searchParams.getAll("ticket") ?? [];
    let want;
    if (tickets.length && !req.headers.authorization) {
      // The browser's own socket: a browser cannot carry the machine token, so the web layer
      // -- which checked the GitHub session -- signs a thirty-second ticket over the exact
      // target and appends it LAST (policy.mjs socketTicket). What precedes it is what was
      // signed, and is all the route rule below ever sees. Off until previewOrigin is set.
      if (!config.previewOrigin) return reject(socket, 401);
      if (req.headers.origin !== config.previewOrigin) return reject(socket, 403);
      const cut = req.url.search(/[?&]ticket=/);
      want = req.url.slice(0, cut);
      // cut < 0: the parser found a ticket the wire does not spell literally (tick%65t=).
      // What was signed is the literal text, so that is refused here, not by luck below.
      const nonce = cut >= 0 && tickets.length === 1 && req.url.slice(cut + 8) === tickets[0]
        ? socketTicketNonce(config.token, want, tickets[0], now()) : null;
      for (const [used, until] of admitted) if (until < now()) admitted.delete(used);
      if (!nonce || admitted.has(nonce)) return reject(socket, 401);
      admitted.set(nonce, Number(tickets[0].split(".")[0]));
    } else {
      // The machine path: the same lock as HTTP, then the gateway's own Origin only.
      if (!authorized(req, config)) return reject(socket, 401);
      if (!url || req.headers.origin !== config.origin) return reject(socket, 403);
      want = req.url;
    }
    // Two socket routes at this tag: the reference's live grid and the wire. policy.mjs'
    // socketTarget holds the rule -- the exact path, no query (the whole subscription is the
    // frame, not the URL) -- and is the SAME function the web layer's ticket signer consults,
    // so the two can never drift about what may be opened. A subprotocol is refused: neither
    // upstream speaks one. Anything unmatched is 404, before any upstream is consulted.
    const route = req.method === "GET" && req.headers["sec-websocket-protocol"] === undefined
      ? socketTarget(want, config.origin) : null;
    if (!route) return reject(socket, 404);
    const news = route === "/news/ws/news";
    // Nothing to subscribe to: the operator has approved no feeds, so there is no wire socket
    // to open. 503, not 404 -- the route exists, the upstream is simply not configured, which
    // is what verify.mjs's own probe distinguishes.
    if (news && !Object.keys(config.feeds).length) return reject(socket, 503);
    // The socket cap is checked BEFORE handleUpgrade: a refused upgrade never allocates a client.
    if (sockets >= config.maxSockets) return reject(socket, 429);
    wss.handleUpgrade(req, socket, head, client => {
      sockets++;
      // The 10 s handshake deadline set above must not go on applying to an open socket.
      socket.setTimeout(0);
      let upstream = null, pending = null, subscribed = false;
      const close = () => { client.terminate(); upstream?.terminate(); };
      // No lifetime: a socket stays open while its client answers. A ping every pingMs that
      // goes unanswered by the next one closes it, so a peer that vanished without closing (a
      // sleeping tablet, a dropped link) hands its slot back. A shorter deadline applies to the
      // first frame -- a client that opens and says nothing holds a slot for free.
      let alive = true;
      client.on("pong", () => { alive = true; });
      const heartbeat = setInterval(() => { if (!alive) return close(); alive = false; client.ping(); }, pingMs);
      const initial = setTimeout(close, firstFrameMs);
      client.once("close", () => {
        sockets--; clearInterval(heartbeat); clearTimeout(initial); upstream?.terminate();
      });
      client.on("error", close);
      client.on("message", (data, binary) => {
        if (news) {
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
            // The door is the only trust boundary: rss-ticker is unauthenticated on the tailnet,
            // so the door forwards the {"feeds"} reply and approved-feed articles, nothing else.
            let out;
            try { out = JSON.parse(message.toString()); } catch { return close(); }
            if (out && Object.keys(out).join() === "feeds" ||
                approvedIds.has(out?.feed_id)) client.send(message, { binary: false });
          });
          upstream.on("error", close);
          upstream.once("close", close);
          if (upstream.readyState === WebSocket.OPEN) return upstream.send(frame);
          upstream.once("open", () => {
            if (client.readyState === WebSocket.OPEN) upstream.send(frame);
          });
          return;
        }
        // A params frame on open AND on every symbol change over the same socket, re-validated
        // each time. The reference is a keyless local fixture, so there is no vendor meter here;
        // maxSockets is the whole budget.
        if (binary) return close();
        const frame = refSubscription(data);
        if (!frame) return close();
        clearTimeout(initial);
        if (!upstream) {
          // Connect upstream ONLY on the first validated frame.
          try { upstream = openRef(config); } catch { return close(); }
          upstream.on("message", (message, isBinary) => {
            if (isBinary || message.length > MAX_SOCKET || client.readyState !== WebSocket.OPEN ||
                client.bufferedAmount > 262144) return close();
            client.send(message, { binary: false });
          });
          upstream.on("error", close);
          upstream.once("close", close);
          // Until the upstream opens, only the latest validated frame is held (a symbol
          // change before open supersedes the first subscription; nothing queues).
          upstream.once("open", () => {
            if (pending !== null && client.readyState === WebSocket.OPEN) upstream.send(pending);
            pending = null;
          });
        }
        if (upstream.readyState !== WebSocket.OPEN) { pending = frame; return; }
        if (upstream.bufferedAmount > 262144) return close();
        upstream.send(frame);
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
