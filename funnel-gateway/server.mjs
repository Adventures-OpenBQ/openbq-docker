// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// openbq-docker v10.0.0. Ported from bdobb-dev/openbb-docker v8.0.3 (775354f)
// funnel-gateway/server.mjs with the /ai (Rita) family and its SOCKS5 dialer removed; the
// /grid family (live-grid, the `live` profile) from v10.1.7 (d606169): e8c1239, 7212a1d,
// b9545f5, d32966d, dc61be8, d7ec9d1 -- gated here by settings.json's "liveGrid".
// The socket door also serves the reference's /ref/live_grid_ws, which came down to v3/v4
// with the reference backend.

import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { gzip } from "node:zlib";
import { once } from "node:events";
import { WebSocket, WebSocketServer } from "ws";
import { ritaRoute, ritaQuery, ritaAgents, ritaFeedback, RITA_FEEDBACK_MAX } from "./rita-policy.mjs";
import { mcpRoute, mcpMessage, MCP_SESSION_RE, MCP_VERSION_RE } from "./mcp-policy.mjs";
import { tableRoute, tableControlRoute, TABLE_CONTROL_CONCURRENCY, TABLE_RESPONSE_BYTES, upstreamPath, newsSubscription, liveGridSubscription, refSubscription, socketTarget, socketTicket, socketTicketNonce, stateFile } from "./policy.mjs";

const MAX_BODY = 2 * 1024 * 1024;
// The root manifests are static catalogue documents, not data: openbq-api's widgets.json is
// 5.0 MB (998 widgets). They get their own cap; every other path keeps MAX_BODY.
const MANIFESTS = new Set(["/api/widgets.json", "/api/apps.json", "/ref/widgets.json", "/ref/apps.json"]);
const MANIFEST_MAX = 16 * 1024 * 1024; // ponytail: manifests are buffered and parsed (~6x their size at peak); 8 concurrent 16 MiB manifests could pass mem_limit 512m — stream them unparsed if that ever matters.
const MAX_SOCKET = 65536;
/**
 * A hard ceiling per grid socket on validated CLIENT frames on /grid/live_grid_ws, for as
 * long as the socket is open. It is NOT configurable. With no daily or per-minute budget
 * (removed 2026-10-17) it and maxSockets are what bound the paid seeds one socket can ask for.
 * 60 is generous for a human changing a watchlist and far below what a script can send.
 * /grid/ta_chart_ws's upstream pushes are not capped: a tick chart streams while it is open.
 * The wire's socket can never reach it -- its second frame is fatal by contract.
 */
const FRAME_CAP = 60;
/**
 * The documents the client PROBES rather than requires. dataClient.ts fetches both with
 * `allow404` and matches on the literal status (`res.status === 404 && allow404`), resolving
 * "this backend ships no apps" and "those metadata columns are blank". On THIS line live-grid
 * really serves both, so the relay is the older-upstream fallback rather than the normal
 * answer -- it stays because the client's contract has not changed and the door's 502 would
 * still make fetchAppsJson throw where it is built to degrade. The relayed 404 carries the
 * door's OWN body, never the upstream's, and every other non-200 -- a 404 on any other route
 * included -- stays a 502.
 */
/**
 * The packaged desktop app's webview origins (V10-P1, user ruling 2026-10-15). Tauri's http
 * plugin stamps one of these on every request it makes (tauri://localhost on macOS, iOS and
 * Linux; http://tauri.localhost on Windows and Android), and the webview's own WebSocket
 * carries the same one. An Origin is never a credential: these pass the Origin rule only
 * behind the Bearer lock, or on a ticket minted for that same origin (/grid/ws_ticket).
 * The dev server's http://localhost:1420 is deliberately not one of them.
 */
export const DESKTOP_ORIGINS = new Set(["tauri://localhost", "http://tauri.localhost"]);
const OPTIONAL_DOCS = new Set(["/grid/apps.json", "/grid/symbol_meta"]);
const digest = value => createHash("sha256").update(value).digest();
function authorized(req, config) {
  const values = req.rawHeaders.filter((_, i) => i % 2 === 0 && req.rawHeaders[i].toLowerCase() === "authorization");
  return values.length === 1 && typeof req.headers.authorization === "string" &&
    timingSafeEqual(digest(req.headers.authorization), digest(`Bearer ${config.token}`));
}
function requestUrl(req, config) {
  if (req.headers.host !== new URL(config.origin).host || !req.url?.startsWith("/") ||
      req.url.startsWith("//") || req.url.includes("#")) return null;
  const [raw, ...query] = req.url.split("?");
  // D8: WHATWG URL parsers (WebKit's among them) percent-encode "^" in a path, so removing an
  // index symbol arrives as /grid/api/subscriptions/%5EGSPC. That one escape, in that one
  // one-symbol path, is read as the caret; every other "%" anywhere is still refused.
  const path = /^\/grid\/api\/subscriptions\/[^/]+$/.test(raw) ? raw.replace(/%5e/gi, "^") : raw;
  if (/[%\\#]/.test(path)) return null;
  const url = new URL([path, ...query].join("?"), config.origin);
  // Whether the parser escapes "^" differs by Node version (22 keeps it, 26 writes %5E); path holds
  // no "%", so any %5E in the pathname is an escaped caret.
  return url.pathname.replaceAll("%5E", "^") === path && url.origin === config.origin ? url : null;
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
/**
 * A root manifest, gzipped for a caller that accepts gzip. openbq-api's 5.2 MB widgets.json
 * crossed Funnel's public ingress at ~0.3 MB/s on 2026-10-18 (18-60+ s), past BDOBB's web
 * layer's 12 s upstream timeout; its fetch sends Accept-Encoding: gzip and decodes the answer.
 */
const gzipAsync = promisify(gzip);
async function replyManifest(req, res, value) {
  // ponytail: substring match ignores "gzip;q=0", as BDOBB's web layer does; parse q-values if a caller ever sends it.
  if (!/\bgzip\b/i.test(req.headers["accept-encoding"] ?? "")) return reply(res, 200, value);
  const body = await gzipAsync(JSON.stringify(value));
  res.writeHead(200, { ...COMMON, "Content-Type": "application/json", "Content-Encoding": "gzip", Vary: "Accept-Encoding" });
  res.end(body);
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
// Four upstreams at this tag (openbq-docker serves no /ai). /api/... -> openbq-api, plain HTTP
// on the bridge, behind the stack's Basic pair; the prefix is stripped ("/api/api/v1/x" ->
// "/api/v1/x") and the credential injected. /grid/... -> live-grid (the opt-in `live`
// profile), the same way and behind the SAME pair (below). /news/... -> rss-ticker, on the
// tailnet, no credential (it has none). /ref/... -> the keyless reference fixture, "/ref"
// stripped, NO Authorization header. Nothing the caller sent goes with any of them.
// The upstream URL is built by concatenation, never by resolving the path against the origin,
// so the host can only ever be the fixed origin (a "//host" path would otherwise replace it).
function target(path, config) {
  if (path.startsWith("/api/")) {
    return { url: new URL(config.apiOrigin + path.slice(4)), options: {},
      headers: { Authorization: config.apiAuthorization, Accept: "application/json" } };
  }
  // live-grid (v10; ported from bdobb-dev/openbb-docker e8c1239/b9545f5): a sibling
  // container on the same openbq-internal bridge as openbq-api, so plain HTTP and no dialler
  // of its own -- and guarded by the SAME Basic pair, which is why the credential is injected
  // here too. live-grid appends BasicAuthMiddleware to its whole app (live-grid/app/auth.py,
  // reading OPENBB_API_AUTH and the pair from the credentials.env compose loads into it), so
  // with the lock on a request without the credential is refused on EVERY route, its
  // manifest and its websocket handshake included.
  if (path.startsWith("/grid/")) {
    return { url: new URL(config.gridOrigin + path.slice(5)), options: {},
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
 * The grid's socket (Ep. 10), opened once a client's first params frame has passed
 * liveGridSubscription -- so a client that opens and says nothing, or says something
 * invalid, never opens anything upstream. `ws://`, not `wss://`: live-grid listens on the
 * bridge with no TLS of its own, exactly like openbq-api. The upgrade carries the stack's
 * Basic pair for the same reason the HTTP branch does -- live-grid's auth middleware sits in
 * front of its websocket route too, and refuses the handshake before accept without it.
 * Same bounds as the wire's socket: MAX_SOCKET on what the upstream can push, compression
 * off (a compressed frame's expanded size is not what maxPayload measures), no redirect, and
 * a 10s handshake deadline. `Origin` is sent for the same reason connectNews sends it -- so
 * the dial this door makes is spelled the same way on both sockets rather than differing for
 * no stated reason. live-grid does not check it (its CORSMiddleware is allow_origins=["*"]
 * and Starlette's CORS layer does not see a websocket scope at all; BasicAuthMiddleware is
 * the whole gate), so this is symmetry, not a guard.
 */
export function connectGrid(config, path = "/live_grid_ws") {
  // `path` is live-grid's own route, the door's /grid prefix already stripped -- and for
  // /ta_chart_ws it carries the query socketTarget re-serialised, because that socket takes
  // its whole parameter set from the URL and never reads a client frame. One dialler for
  // both: the bounds, the credential and the Origin are identical, only the target differs.
  const url = new URL(path, config.gridOrigin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(url, {
    headers: { Authorization: config.apiAuthorization, Origin: config.gridOrigin },
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
        response.destroy();
        // The STATUS travels on the error, never the body: the handler needs to tell a 404
        // from every other refusal for the optional documents (OPTIONAL_DOCS below), and
        // nothing upstream wrote may reach the caller either way.
        const failure = new Error("Invalid upstream response");
        failure.status = response.statusCode;
        return rejectPromise(failure);
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
 * live-grid's Subscriptions page and its watchlist API, behind this door (V10-P5, user
 * request 2026-10-13). Not in policy.mjs: that file is vendored by BDOBB's web layer under a
 * hash test, and the web preview cannot use these routes anyway -- its browser never holds
 * this door's token, and a framed page gets the credential only from the desktop app's
 * openbb-connect handshake (BDOBB useWidgetMessages.ts).
 *
 *   GET    /grid/subscriptions                -> the page (SUBSCRIPTIONS_PAGE), no query
 *   GET    /grid/api/subscriptions            -> the watchlist, no query
 *   POST   /grid/api/subscriptions            -> add {"symbol": SYMBOL}, JSON, <= 1 KiB
 *   DELETE /grid/api/subscriptions/<SYMBOL>   -> remove
 *
 * SYMBOL is the grid's one-symbol grammar. What leaves is re-serialised: the POST body is
 * rebuilt from the validated symbol, never relayed. live-grid's own answers are relayed for
 * 200 and 201 (its watchlist payload, JSON, bounded); its refusals become this door's own
 * fixed messages for the four it gives (404, 409, 422, 507), so the page can say why.
 */
export const SUBSCRIPTIONS_PAGE = "/grid/subscriptions";
const SUBSCRIPTION_SYMBOL_RE = /^[A-Za-z0-9.^_-]{1,24}$/;
const SUBSCRIPTION_REFUSALS = {
  404: "That symbol is not on the watchlist.",
  409: "That symbol is already subscribed.",
  422: "Not a symbol.",
  507: "The symbol cap is reached; remove a symbol first.",
};
export function subscriptionRoute(url, method) {
  if (url.search) return null;
  if (url.pathname === "/grid/api/subscriptions") {
    return method === "GET" || method === "POST" ? { method, path: "/api/subscriptions" } : null;
  }
  const one = /^\/grid\/api\/subscriptions\/([^/]+)$/.exec(url.pathname);
  if (one && method === "DELETE" && SUBSCRIPTION_SYMBOL_RE.test(one[1].replaceAll("%5E", "^"))) {
    return { method, path: `/api/subscriptions/${one[1].replaceAll("%5E", "^")}` };
  }
  return null;
}
/** One bounded JSON exchange with live-grid: the status, and the body only on 200/201. */
export async function sendGrid(method, path, body, config, signal) {
  const url = new URL(path, config.gridOrigin);
  const headers = { Authorization: config.apiAuthorization, Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["Content-Length"] = String(Buffer.byteLength(body));
  }
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(url, { method, headers, signal }, response => {
      const ok = response.statusCode === 200 || response.statusCode === 201;
      if (!ok || !/^application\/json(?:\s*;|$)/i.test(response.headers["content-type"] ?? "")) {
        response.destroy();
        return resolve({ status: ok ? 502 : response.statusCode });
      }
      let size = 0; const parts = [];
      response.on("data", chunk => {
        size += chunk.length;
        if (size > MAX_BODY) { response.destroy(); rejectPromise(new Error("Body limit")); }
        else parts.push(chunk);
      });
      response.on("error", rejectPromise);
      response.on("end", () => {
        try { resolve({ status: response.statusCode, json: JSON.parse(Buffer.concat(parts).toString("utf8")) }); }
        catch { rejectPromise(new Error("Invalid JSON")); }
      });
    });
    request.once("error", rejectPromise);
    request.end(body);
  });
}
/** The page itself, as text: live-grid's /subscriptions, HTML only, at most 64 KiB. */
export async function getGridPage(config, signal) {
  const url = new URL("/subscriptions", config.gridOrigin);
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(url, { method: "GET", signal,
      headers: { Authorization: config.apiAuthorization, Accept: "text/html" } }, response => {
      if (response.statusCode !== 200 || !/^text\/html(?:\s*;|$)/i.test(response.headers["content-type"] ?? "")) {
        response.destroy(); return rejectPromise(new Error("Invalid upstream page"));
      }
      let size = 0; const parts = [];
      response.on("data", chunk => {
        size += chunk.length;
        if (size > 65536) { response.destroy(); rejectPromise(new Error("Body limit")); }
        else parts.push(chunk);
      });
      response.on("error", rejectPromise);
      response.on("end", () => resolve(Buffer.concat(parts).toString("utf8")));
    });
    request.once("error", rejectPromise);
    request.end();
  });
}
// The framed page runs script, so it gets a policy of its own: inline script and style (the
// page is one file), fetch to this origin only, nothing else loaded, no base or form target.
// No frame-ancestors: being framed by the app is the point.
const PAGE_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  "connect-src 'self'; base-uri 'none'; form-action 'none'";
function replyPage(res, html) {
  res.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Security-Policy": PAGE_CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
  });
  res.end(html);
}
/**
 * The one widget whose endpoint the door rewrites: live-grid names its Subscriptions page by
 * LIVE_GRID_PUBLIC_URL or, unset (the compose default), by the address the request came in on
 * -- here the internal compose address. Relayed through /grid, the frame must open THIS door's page --
 * an absolute URL on this origin, which is also what lets BDOBB hand it the credential
 * (WidgetCard.tsx messagingFor: frame origin === backend origin).
 */
export function rewriteGridWidgets(spec, config) {
  const sub = spec?.subscriptions;
  if (sub && typeof sub === "object" && sub.type === "iframe") {
    sub.endpoint = config.origin + SUBSCRIPTIONS_PAGE;
  }
  return spec;
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

/**
 * Rita (rita-policy.mjs), the door's one streamed route. Her query is JSON in (1 MiB) and her
 * event stream out and nothing else of hers, five minutes and 16 MiB a turn (the web layer's
 * Vercel function stops at 300 s too). No header of the caller's goes upstream: she is sent
 * the rewritten body alone. Ported from bdobb-dev/openbb-docker v8.0.3 (775354f) handleQuery,
 * now over the bridge to openbq-rita-door rather than the tailnet.
 */
const RITA_QUERY_MAX = 1024 * 1024, RITA_STREAM_MAX = 16 * 1024 * 1024, RITA_STREAM_MS = 300000;
const RITA_AGENTS_MAX = 65536, RITA_HOUR_MS = 3600000;
// The Spark's vLLM runs four sequences at most; two turns leave room for the desktop's own Rita.
const RITA_CONCURRENT = 2;
export function getRitaAgents(config, signal) {
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(new URL("/agents.json", config.ritaUpstream), { method: "GET", signal,
      headers: { Accept: "application/json" } }, response => {
      if (response.statusCode !== 200 || !/^application\/json(?:\s*;|$)/i.test(response.headers["content-type"] ?? "")) {
        response.destroy(); return rejectPromise(new Error("Rita refused"));
      }
      const parts = []; let size = 0;
      response.on("data", chunk => { size += chunk.length; if (size > RITA_AGENTS_MAX) response.destroy(new Error("Body limit")); else parts.push(chunk); });
      response.on("error", rejectPromise);
      response.on("end", () => { try { resolve(JSON.parse(Buffer.concat(parts).toString("utf8"))); } catch (e) { rejectPromise(e); } });
    });
    request.once("error", rejectPromise);
    request.end();
  });
}
/** Rita's one POST. The caller checks the status and the content type, and owns the stream. */
export function postRita(body, config, signal) {
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(new URL("/v1/query", config.ritaUpstream), { method: "POST", signal,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", "Content-Length": body.length } }, resolve);
    request.once("error", rejectPromise);
    request.end(body);
  });
}
/** Her feedback POST, charged to `principal`: a web user's github:<id> goes with it; the desktop's bucket sends none. */
export function postRitaFeedback(body, principal, config, signal) {
  return new Promise((resolve, rejectPromise) => {
    const headers = { "Content-Type": "application/json", "Content-Length": body.length,
      ...(principal.startsWith("github:") ? { "X-Rita-Principal": principal } : {}) };
    const request = httpRequest(new URL("/v1/feedback", config.ritaUpstream), { method: "POST", signal, headers }, resolve);
    request.once("error", rejectPromise);
    request.end(body);
  });
}
/**
 * Who a query is charged to: the web layer's verified GitHub id, sent once as X-Rita-Principal
 * (github:<id>), or the desktop's one shared bucket when absent. Behind the Bearer lock, so only
 * a token holder can name one -- enough for a rate limit, which is all it decides here.
 */
function ritaPrincipal(req) {
  const count = req.rawHeaders.filter((v, i) => i % 2 === 0 && v.toLowerCase() === "x-rita-principal").length;
  if (count === 0) return "desktop";
  const value = req.headers["x-rita-principal"];
  return count === 1 && /^github:[1-9][0-9]{0,19}$/.test(value ?? "") ? value : null;
}

/**
 * openbq-mcp (mcp-policy.mjs): one JSON-RPC message in (1 MiB), its JSON or event-stream answer
 * out (8 MiB, two minutes: call_tool runs an OpenBB endpoint). Only the protocol's own headers
 * travel, both ways, and a session id only to the principal whose initialize opened it.
 */
const MCP_BODY_MAX = 1024 * 1024, MCP_REPLY_MAX = 8 * 1024 * 1024, MCP_MS = 120000, MCP_SESSIONS = 5000;
/** Who an MCP message is charged to: X-Preview-Principal github:<id> once, or the desktop's bucket. */
function previewPrincipal(req) {
  const count = req.rawHeaders.filter((v, i) => i % 2 === 0 && v.toLowerCase() === "x-preview-principal").length;
  if (count === 0) return "desktop";
  const value = req.headers["x-preview-principal"];
  return count === 1 && /^github:[1-9][0-9]{0,19}$/.test(value ?? "") ? value : null;
}

/** Test dependency injection is not exposed through environment variables. */
export function createGateway(config, { requestJson = getJson, openNews = connectNews,
  openGrid = connectGrid, openRef = connectRef, sendSubscription = sendGrid, fetchPage = getGridPage,
  postQuery = postRita, now = Date.now, pingMs = 30000, firstFrameMs = 10000, requestMs = 12000 } = {}) {
  let inflight = 0, controlInflight = 0, sockets = 0;
  // Rita's limits: turns open now (all, and whose), and each principal's query times this hour.
  // ponytail: in memory, so a restart forgets the hour; persist it if the cap ever has to survive one.
  // MCP sessions: id -> the principal whose initialize opened it (oldest dropped past MCP_SESSIONS),
  // and each principal's message times this hour. ponytail: in memory, like Rita's.
  const mcpSessions = new Map(), mcpUse = new Map();
  async function handleMcp(req, res, url) {
    if (!mcpRoute(url, req.method)) return reply(res, 404);
    const principal = previewPrincipal(req);
    if (!principal) return reply(res, 400);
    const session = req.headers["mcp-session-id"], version = req.headers["mcp-protocol-version"];
    if ((session !== undefined && !MCP_SESSION_RE.test(session)) || (version !== undefined && !MCP_VERSION_RE.test(version))) return reply(res, 400);
    // An id this door never saw opened, or one another principal opened: MCP's own answer for a
    // session the server does not know, so the client re-initializes.
    if (session !== undefined && mcpSessions.get(session) !== principal) return reply(res, 404);
    if (inflight >= config.maxConcurrent) return reply(res, 429);
    if (mcpUse.size > 1000) for (const [who, times] of mcpUse) if (!times.some(at => now() - at < RITA_HOUR_MS)) mcpUse.delete(who);
    const recent = (mcpUse.get(principal) ?? []).filter(at => now() - at < RITA_HOUR_MS);
    if (recent.length >= config.mcpPerHour) { mcpUse.set(principal, recent); return reply(res, 429); }
    const raw = await jsonBody(req, MCP_BODY_MAX);
    if (typeof raw === "number") { if (raw === 413) res.setHeader("Connection", "close"); return reply(res, raw); }
    const message = mcpMessage(raw);
    if (message.error) return reply(res, 400);
    // Reading the body yields; another request may have taken the slot.
    if (inflight >= config.maxConcurrent) return reply(res, 429);
    // Re-read the hour: a parallel message from the same user may have been charged while this body was read.
    const charged = (mcpUse.get(principal) ?? []).filter(at => now() - at < RITA_HOUR_MS);
    if (charged.length >= config.mcpPerHour) { mcpUse.set(principal, charged); return reply(res, 429); }
    mcpUse.set(principal, [...charged, now()]);
    inflight++;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), MCP_MS);
    const disconnect = () => { if (!res.writableEnded) controller.abort(); };
    res.once("close", disconnect);
    try {
      const headers = { "Content-Type": "application/json", Accept: "application/json, text/event-stream",
        ...(version ? { "MCP-Protocol-Version": version } : {}), ...(session ? { "Mcp-Session-Id": session } : {}) };
      const response = await fetch(new URL("/mcp", config.mcpUpstream), { method: "POST", headers, body: message.body,
        redirect: "error", signal: controller.signal });
      if (response.status === 202) { await response.body?.cancel(); res.writeHead(202, COMMON); return res.end(); }
      const type = response.headers.get("content-type") ?? "";
      const stream = /^text\/event-stream(?:\s*;|$)/i.test(type);
      if (![200, 400, 404].includes(response.status) || !(stream || /^application\/json(?:\s*;|$)/i.test(type))) {
        await response.body?.cancel(); return reply(res, 502);
      }
      const opened = response.headers.get("mcp-session-id");
      if (message.method === "initialize" && opened && MCP_SESSION_RE.test(opened)) {
        if (mcpSessions.size >= MCP_SESSIONS) mcpSessions.delete(mcpSessions.keys().next().value);
        mcpSessions.set(opened, principal);
      }
      if (response.status === 404 && session) mcpSessions.delete(session);
      res.writeHead(response.status, { ...COMMON, "Content-Type": stream ? "text/event-stream; charset=utf-8" : "application/json",
        ...(opened && MCP_SESSION_RE.test(opened) ? { "Mcp-Session-Id": opened } : {}), ...(stream ? { "X-Accel-Buffering": "no" } : {}) });
      const aborted = once(controller.signal, "abort").catch(() => {});
      let size = 0;
      for await (const chunk of response.body ?? []) {
        size += chunk.length; if (size > MCP_REPLY_MAX) return res.destroy();
        if (!res.write(chunk) && !controller.signal.aborted) await Promise.race([once(res, "drain"), aborted]);
        if (controller.signal.aborted) return res.destroy();
      }
      res.end();
    } finally { clearTimeout(timer); res.off("close", disconnect); controller.abort(); inflight--; }
  }
  let ritaInflight = 0;
  const ritaBusy = new Set(), ritaUse = new Map();
  async function handleRita(req, res, url) {
    const route = ritaRoute(url, req.method);
    if (!route) return reply(res, 404);
    const principal = ritaPrincipal(req);
    if (!principal) return reply(res, 400);
    if (route === "agents") {
      if (req.headers["transfer-encoding"] || (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
      const doc = ritaAgents(await getRitaAgents(config, AbortSignal.timeout(requestMs)), config.ritaModel);
      return doc ? reply(res, 200, doc) : reply(res, 502);
    }
    // Only a token holder can name a principal, but it can name many: past 1000, sweep the hour.
    if (ritaUse.size > 1000) for (const [who, times] of ritaUse) if (!times.some(at => now() - at < RITA_HOUR_MS)) ritaUse.delete(who);
    const recent = (ritaUse.get(principal) ?? []).filter(at => now() - at < RITA_HOUR_MS);
    if (recent.length) ritaUse.set(principal, recent); else ritaUse.delete(principal);
    if (route === "feedback") {
      // Charged to the hour like a query, but no turn slot: one small POST, not a stream.
      if (recent.length >= config.ritaPerHour) return reply(res, 429);
      const raw = await jsonBody(req, RITA_FEEDBACK_MAX);
      if (typeof raw === "number") { if (raw === 413) res.setHeader("Connection", "close"); return reply(res, raw); }
      const body = ritaFeedback(raw);
      if (!body) return reply(res, 400);
      ritaUse.set(principal, [...recent, now()]);
      const upstream = await postRitaFeedback(Buffer.from(JSON.stringify(body)), principal, config, AbortSignal.timeout(requestMs));
      upstream.resume();
      if (upstream.statusCode !== 204) return reply(res, 502);
      res.writeHead(204, COMMON);
      return res.end();
    }
    if (ritaInflight >= RITA_CONCURRENT || ritaBusy.has(principal)) return reply(res, 429);
    if (recent.length >= config.ritaPerHour) return reply(res, 429);
    ritaInflight++; ritaBusy.add(principal);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RITA_STREAM_MS);
    const disconnect = () => controller.abort();
    res.once("close", disconnect);
    try {
      const raw = await jsonBody(req, RITA_QUERY_MAX);
      if (typeof raw === "number") { if (raw === 413) res.setHeader("Connection", "close"); return reply(res, raw); }
      const body = ritaQuery(raw, config.ritaModel);
      if (!body) return reply(res, 400);
      // Charged once the body is one she could be sent: a refused body costs nothing.
      ritaUse.set(principal, [...recent, now()]);
      const upstream = await postQuery(Buffer.from(JSON.stringify(body)), config, controller.signal);
      if (upstream.statusCode !== 200 || !/^text\/event-stream(?:\s*;|$)/i.test(upstream.headers["content-type"] ?? "")) {
        upstream.destroy(); return reply(res, 502);
      }
      res.writeHead(200, { ...COMMON, "Content-Type": "text/event-stream; charset=utf-8", "X-Accel-Buffering": "no" });
      // One abort listener for the whole turn, not one per drain wait.
      const aborted = once(controller.signal, "abort").catch(() => {});
      let size = 0;
      for await (const chunk of upstream) {
        // Past the cap the stream is CUT, so the client cannot read a truncated turn as a whole one.
        size += chunk.length; if (size > RITA_STREAM_MAX) return res.destroy();
        // A slow client must not let her chunks pile up in this process: wait for the drain,
        // or for the abort (disconnect or the five-minute cap), whichever comes first.
        if (!res.write(chunk) && !controller.signal.aborted) await Promise.race([once(res, "drain"), aborted]);
        if (controller.signal.aborted) return res.destroy();
      }
      res.end();
    } finally {
      clearTimeout(timer); res.off("close", disconnect); controller.abort();
      ritaInflight--; ritaBusy.delete(principal);
    }
  }
  const approvedIds = new Set(Object.values(config.feeds));
  // Ticket nonces already admitted, until each ticket's own expiry: single use.
  const admitted = new Map();
  // The Subscriptions page, fetched from live-grid once and kept: it is the one route served
  // before the lock (below), so an unauthenticated caller must cost no upstream dial. A failed fetch is held for PAGE_RETRY_MS (D11: otherwise
  // every anonymous request while live-grid is down is one more dial carrying the Basic pair),
  // then the next request retries.
  const PAGE_RETRY_MS = 5000;
  let page = null, pageFailedAt = -Infinity;
  function subscriptionsPage() {
    if (!page && now() - pageFailedAt < PAGE_RETRY_MS) return Promise.reject(new Error("page fetch held"));
    if (!page) page = fetchPage(config, AbortSignal.timeout(10000))
      .catch(error => { page = null; pageFailedAt = now(); throw error; });
    return page;
  }
  async function handleSubscriptions(req, res, route) {
    if (!config.gridOrigin) return reply(res, 503);
    if (inflight >= config.maxConcurrent) return reply(res, 429);
    let body;
    if (route.method === "POST") {
      const raw = await jsonBody(req, 1024);
      if (typeof raw === "number") return reply(res, raw);
      const symbol = JSON.parse(raw.toString("utf8"))?.symbol;
      if (typeof symbol !== "string" || !SUBSCRIPTION_SYMBOL_RE.test(symbol.trim())) {
        return reply(res, 422, { detail: SUBSCRIPTION_REFUSALS[422] });
      }
      body = JSON.stringify({ symbol: symbol.trim() });
    } else if (req.headers["transfer-encoding"] ||
               (req.headers["content-length"] && req.headers["content-length"] !== "0")) {
      return reply(res, 405);
    }
    inflight++;
    try {
      const answer = await sendSubscription(route.method, route.path, body, config, AbortSignal.timeout(12000));
      if (answer.json !== undefined) return reply(res, answer.status, answer.json);
      const message = SUBSCRIPTION_REFUSALS[answer.status];
      return message ? reply(res, answer.status, { detail: message }) : reply(res, 502);
    } finally { inflight--; }
  }
  const wss = new WebSocketServer({ noServer: true, maxPayload: MAX_SOCKET, perMessageDeflate: false });
  const server = createServer({ maxHeaderSize: 16384, requestTimeout: 15000, headersTimeout: 10000,
    keepAliveTimeout: 5000 }, async (req, res) => {
    try {
      // The ONE exception to "the lock precedes everything": the Subscriptions page. A frame
      // is a navigation, and a navigation cannot carry the Bearer token, so the page loads
      // without it -- then asks the app for the credential (openbb-connect) and sends it on
      // every watchlist call, which ARE behind the lock. The page holds no data and no
      // secret; it is served from memory after the first fetch, GET only, no query, no
      // body, on this door's own Host, before any other route is consulted.
      // With live-grid off there is no page, and no exception: the lock answers first, as for
      // every path at v9, so an anonymous caller learns nothing about the profile (D12).
      if (req.method === "GET" && req.url === SUBSCRIPTIONS_PAGE && config.gridOrigin) {
        const pageUrl = requestUrl(req, config);
        if (!pageUrl) return reply(res, 421);
        if (req.headers["transfer-encoding"] ||
            (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
        return replyPage(res, await subscriptionsPage());
      }
      // The lock precedes route discovery, health, Host and Origin validation.
      if (!authorized(req, config)) return reply(res, 401);
      const url = requestUrl(req, config);
      if (!url) return reply(res, 421);
      const origin = req.headers.origin;
      if (origin && origin !== config.origin && !DESKTOP_ORIGINS.has(origin)) return reply(res, 403);
      if (req.method === "GET" && req.url === SUBSCRIPTIONS_PAGE) return reply(res, 503);  // live-grid off
      if (url.pathname.startsWith("/state/")) {
        return await handleState(req, res, url, config);
      }
      if (url.pathname.startsWith("/grid/api/subscriptions")) {
        const route = subscriptionRoute(url, req.method);
        if (!route) return reply(res, 404);
        return await handleSubscriptions(req, res, route);
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
      // Off ("rita" unset), /ai is what it always was here: unmatched, its POST a 405.
      if (config.ritaUpstream && url.pathname.startsWith("/ai/")) return await handleRita(req, res, url);
      // Off ("mcp" unset), /mcp is unmatched, its POST a 405, as at every earlier tag.
      if (config.mcpUpstream && (url.pathname === "/mcp" || url.pathname.startsWith("/mcp/"))) return await handleMcp(req, res, url);
      if (req.method !== "GET" || req.headers["transfer-encoding"] ||
          (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
      if (url.pathname === "/_gateway/health" && !url.search) return reply(res, 200, { ok: true });
      // The desktop's socket ticket (V10-P1). Its webview socket cannot carry the Bearer
      // header, so the app asks here, behind the lock, for a thirty-second single-use ticket
      // over its own Origin plus the one /grid socket it will open -- the same signer as the
      // preview's, over a string no preview ticket is signed over (those begin with "/").
      // The ticket is in the body only; this door logs no request.
      if (url.pathname === "/grid/ws_ticket") {
        if (!DESKTOP_ORIGINS.has(origin)) return reply(res, 403);
        // Every /grid ticket is for a live-grid socket, which answers 503 while it is off (D10).
        if (!config.gridOrigin) return reply(res, 503);
        const keys = [...url.searchParams.keys()];
        const target = keys.length === 1 && keys[0] === "target"
          ? socketTarget(url.searchParams.get("target"), config.origin) : null;
        if (!target?.startsWith("/grid/")) return reply(res, 404);
        return reply(res, 200, { ticket: socketTicket(config.token, origin + target, now()) });
      }
      const path = upstreamPath(url, config);
      if (!path) return reply(res, 404);
      // live-grid is the opt-in `live` profile: until settings.json says it runs
      // ("liveGrid": true), every /grid route answers 503, as /news does without the wire.
      if (path.startsWith("/grid/") && !config.gridOrigin) return reply(res, 503);
      if (inflight >= config.maxConcurrent) return reply(res, 429);
      inflight++;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), requestMs);
      const disconnect = () => { if (!res.writableEnded) controller.abort(); };
      res.once("close", disconnect);
      try {
        const answer = await requestJson(path, config, controller.signal);
        if (MANIFESTS.has(path)) await replyManifest(req, res, answer);
        else reply(res, 200, path === "/grid/widgets.json" ? rewriteGridWidgets(answer, config) : answer);
      }
      catch (failure) {
        // The one status this door relays, and only for the two documents the client probes
        // with allow404 (OPTIONAL_DOCS above). The BODY is still the door's own; anything
        // else -- another route's 404, a 500, a non-JSON answer -- falls through to the 502
        // the outer catch writes.
        if (failure?.status === 404 && OPTIONAL_DOCS.has(path.split("?")[0])) return reply(res, 404);
        throw failure;
      }
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
    let want, nonce = null;
    if (tickets.length && !req.headers.authorization) {
      // The browser's own socket. Relaying it through a Vercel Function bills function time while it is open, and a browser
      // cannot carry the machine token, so the web layer -- which checked the GitHub
      // session -- signs a thirty-second ticket over the exact target and appends it
      // LAST (policy.mjs socketTicket). What precedes it is what was signed, and
      // is all the route checks below ever see. Off until previewOrigin is set.
      // Or the desktop app's webview socket, on a ticket /grid/ws_ticket minted for this
      // same Origin: signed over the Origin plus the target, so it is spendable from no other.
      const desktop = DESKTOP_ORIGINS.has(req.headers.origin);
      if (!desktop && !config.previewOrigin) return reject(socket, 401);
      if (!desktop && req.headers.origin !== config.previewOrigin) return reject(socket, 403);
      const cut = req.url.search(/[?&]ticket=/);
      want = req.url.slice(0, cut);
      // cut < 0: the parser found a ticket the wire does not spell literally (tick%65t=).
      // What was signed is the literal text, so that is refused here, not by luck below.
      nonce = cut >= 0 && tickets.length === 1 && req.url.slice(cut + 8) === tickets[0]
        ? socketTicketNonce(config.token, desktop ? req.headers.origin + want : want, tickets[0], now()) : null;
      for (const [used, until] of admitted) if (until < now()) admitted.delete(used);
      if (!nonce || admitted.has(nonce)) return reject(socket, 401);
      // Recorded below, only once every refusal has passed (D13): a ticket refused for load
      // (429, 503) is not spent, and nothing awaits in between, so it is still single use.
    } else {
      // The machine path: the same lock as HTTP, then the gateway's own Origin only.
      if (!authorized(req, config)) return reject(socket, 401);
      if (!url || req.headers.origin !== config.origin) return reject(socket, 403);
      want = req.url;
    }
    // FOUR socket routes at this tag: the reference's live grid (v3), the wire (Ep. 8), the
    // quote grid (Ep. 10) and this line's tick chart. policy.mjs' socketTarget holds the rule
    // for all four -- the exact path and no query for the first three, whose subscription is
    // a frame, and the path plus /grid/ta_chart's own validated query for the fourth, whose
    // subscription IS the URL -- and it is the SAME function the web layer's ticket signer
    // consults, so the two layers can never drift about what may be opened. It reads the raw
    // request text (`want`, the ticket cut off), never a parsed and re-spelled URL. The target
    // it returns is what gets dialled, so the query that leaves is the one it re-serialised,
    // never the caller's raw string. A subprotocol is refused here: no upstream speaks one,
    // and ws would otherwise have to negotiate it. Anything unmatched is 404, before any
    // upstream is consulted.
    const target = req.method === "GET" && req.headers["sec-websocket-protocol"] === undefined
      ? socketTarget(want, config.origin) : null;
    if (!target) return reject(socket, 404);
    const route = target.split("?")[0];
    const ta = route === "/grid/ta_chart_ws";
    const grid = ta || route === "/grid/live_grid_ws";
    const ref = route === "/ref/live_grid_ws";
    // Nothing to subscribe to: the operator has approved no feeds, so there is no wire socket
    // to open. 503, not 404 -- the route exists, the upstream is simply not configured, which
    // is what verify.mjs's own probe distinguishes. The grid has the same state here: on
    // openbq-docker live-grid is the opt-in `live` compose profile, so until settings.json
    // says it runs ("liveGrid": true, config.mjs) its sockets answer 503 as well.
    if (route === "/news/ws/news" && !Object.keys(config.feeds).length) return reject(socket, 503);
    if (grid && !config.gridOrigin) return reject(socket, 503);
    // The socket cap is checked BEFORE handleUpgrade: an upgrade that is going to be refused
    // must never get as far as allocating a ws client.
    if (sockets >= config.maxSockets) return reject(socket, 429);
    if (nonce) admitted.set(nonce, Number(tickets[0].split(".")[0]));
    wss.handleUpgrade(req, socket, head, client => {
      sockets++;
      // The 10 s handshake deadline set above must not go on applying to an open socket.
      socket.setTimeout(0);
      let upstream, subscribed = false, pending = null, frames = 0;
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
      /**
       * Wiring the upstream leg is identical for all four sockets -- the same size and
       * back-pressure bounds on what it may push, the same teardown in both directions --
       * so it lives here once. Only WHEN it is opened differs: on the first validated
       * frame for the wire, the reference and the quote grid, at upgrade for the tick chart, which has no
       * client frame to wait for.
       */
      const connect = () => {
        try {
          upstream = grid ? openGrid(config, target.slice("/grid".length)) : ref ? openRef(config) : openNews(config);
        } catch { close(); return false; }
        upstream.on("message", (message, isBinary) => {
          if (isBinary || message.length > MAX_SOCKET || client.readyState !== WebSocket.OPEN ||
              client.bufferedAmount > 262144) return close();
          // The door is the only trust boundary for the wire: rss-ticker is unauthenticated on
          // the tailnet, so the door forwards the {"feeds"} reply and approved-feed articles,
          // nothing else. The grid and the reference relay as they are.
          if (!grid && !ref) {
            let out;
            try { out = JSON.parse(message.toString()); } catch { return close(); }
            if (!(out && Object.keys(out).join() === "feeds" || approvedIds.has(out?.feed_id))) return;
          }
          client.send(message, { binary: false });
        });
        upstream.on("error", close);
        upstream.once("close", close);
        return true;
      };
      // The tick chart's socket is PUSH-ONLY. live-grid's /ta_chart_ws reads ws.query_params
      // and then loops on send_json; it never reads a frame. So there is no first frame to
      // wait for -- its deadline is cleared and the upstream is dialled here, with the query
      // socketTarget validated -- and any frame a client does send closes the relay below:
      // live-grid would ignore it, and a door that silently swallows a frame is a door that
      // lies about its contract.
      if (ta) { clearTimeout(initial); if (!connect()) return; }
      client.on("message", (data, binary) => {
        // The wire: one subscription frame, ever -- its protocol needs no second one, so a
        // second frame is a client doing something the contract does not describe. The grid:
        // a params frame on open AND again on every parameter change over the same open
        // socket, which is the protocol live-grid's own consumer loop implements, so a
        // repeat frame is expected here and is RE-VALIDATED rather than fatal. Either way
        // what goes upstream is the frame policy.mjs rebuilt, never the client's own bytes.
        // The tick chart takes no frame at all (see above); the wire takes exactly one. The
        // reference's socket (v3) speaks the grid's protocol -- a params frame on open and on
        // every symbol change, re-validated each time -- but it is a keyless local fixture, so
        // no vendor meter applies: FRAME_CAP bounds it.
        if (binary || ta || (!grid && !ref && subscribed)) return close();
        const frame = grid ? liveGridSubscription(data) : ref ? refSubscription(data) : newsSubscription(data, config);
        if (!frame) return close();
        // FRAME_CAP is the one per-socket bound left (the daily and per-minute budgets were
        // removed 2026-10-17); a frame past it closes the relay, as a frame outside the
        // contract does -- the door has no way to answer 429 on an open socket.
        if (++frames > FRAME_CAP) return close();
        subscribed = true; clearTimeout(initial);
        // Connect upstream ONLY on the first validated frame: an invalid or missing
        // subscription must never open an upstream connection at all. A grid client's
        // later frames reuse the connection this one opened.
        if (!upstream) {
          if (!connect()) return;
          // ONE pending frame is held, and only until the handshake completes. A
          // `once("open")` listener per frame -- which is what a single-frame protocol can
          // afford -- would let a grid client that sends a params frame per parameter change
          // add a closure and a frame to this process for every frame it manages to send
          // during the 10s handshake. Superseding is also the correct protocol: a params
          // frame is the client's whole state, not a delta, so the newest one is the only
          // one live-grid needs to be told.
          upstream.once("open", () => {
            if (pending !== null && client.readyState === WebSocket.OPEN) upstream.send(pending);
            pending = null;
          });
        }
        // The mirror of the upstream->client check above, on the direction THIS row
        // introduced. The wire's socket forwards one frame ever, so it needed no such bound;
        // a grid client legitimately sends a params frame per parameter change for as long as
        // the socket is open, and a live-grid that is not draining would otherwise
        // let `upstream.bufferedAmount` grow without limit inside a read_only container. 256
        // KiB behind is closed rather than queued behind -- the same bound, in the same
        // units, as the other direction.
        if (upstream.bufferedAmount > 262144) return close();
        if (upstream.readyState === WebSocket.OPEN) { pending = null; return upstream.send(frame); }
        pending = frame;
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
