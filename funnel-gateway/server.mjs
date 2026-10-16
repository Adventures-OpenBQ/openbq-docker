// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// openbq-docker v10.0.0. Ported from bdobb-dev/openbb-docker v8.0.3 (775354f)
// funnel-gateway/server.mjs with the /ai (Rita) family and its SOCKS5 dialer removed; the
// /grid family (live-grid, the `live` profile) from v10.1.7 (d606169): e8c1239, 7212a1d,
// b9545f5, d32966d, dc61be8, d7ec9d1 -- gated here by settings.json's "liveGrid".

import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";
import { upstreamPath, newsSubscription, liveGridSubscription, socketTarget, socketTicketNonce, stateFile } from "./policy.mjs";

import { requestState as remoteState } from "./state-store.mjs";

import { temporalRoute, temporalStatus } from "./temporal-policy.mjs";

const MAX_BODY = 2 * 1024 * 1024;
const MAX_SOCKET = 65536;
/**
 * The /grid routes that reach a PAID vendor, and are therefore metered against the very
 * same daily counter as /api/api/v1/**: /grid/ta_chart draws its figure over the same
 * build_series call /grid/chart does, /grid/live_grid calls the EODHD SDK once per symbol
 * in the watchlist (live-grid/app/quotes.py -- and SYMBOL_LIST_RE admits a long list),
 * /grid/symbol_meta's get_meta calls get_fundamentals_data once per symbol that is not in
 * its TTL cache (live-grid/app/symbol_meta.py), and /grid/series and /grid/chart both run
 * build_series -> fetch_series -> openbq-api's historical route (on openbq-docker the obb.eodhd.*
 * namespace, /api/v1/eodhd/<class>/price/historical; on the donor /api/v1/equity/price/historical) with
 * provider=kdb|eodhd (live-grid/app/openbb_client.py) -- the same paid upstream the /api
 * family is metered for reaching.
 *
 * DELIBERATE DEVIATION FROM main, which meters none of them (user ruling on the 2026-09-26
 * review of the v10.0.3 cut, Important 1): without this the door's daily vendor cap is
 * bypassable through /grid at the full per-minute rate, and EODHD quota exhaustion surfaces
 * as stack-wide 502s instead of the door's own 429. Carry it back up the lines.
 *
 * /grid/symbol_meta is metered HERE and was not at v10.0.3. Not a change of mind: that
 * line's live-grid has no such route, so it reached nothing there, and this line's does.
 *
 * Not metered: /grid/widgets.json and /grid/apps.json are live-grid's own documents (no
 * provider is called, the same reason /api's two manifests are exempt), and /grid/ticks
 * reads the in-memory kdb cache.
 *
 * THE SOCKET IS METERED TOO, and it has to be for the sentence above to be true. A params
 * frame on /grid/live_grid_ws makes live-grid seed the vendor for every symbol in it that
 * it has not already seen (live-grid/app/main.py: quotes.seed over the symbols missing from
 * _prev_close), and SYMBOL_LIST_RE admits a long list, so a client that rotates symbol lists
 * over one open socket would otherwise make unbounded paid EODHD calls for the socket's whole
 * lifetime -- the REST cap closed, the socket leg wide open. So EVERY validated frame charges
 * quoteAllowed() once PER SYMBOL out of this same counter, the first one included: the
 * upgrade's spend(6) buys the door's slot and the per-minute budget for that first frame, and
 * nothing from the vendor counter. Exempting the first frame left the hole one level up --
 * socket CHURN rather than frames within a socket -- because ten upgrades a minute fit inside
 * the shipped 60 rpm and would each have carried a free ~40-symbol seed. Frames after the
 * first cost one per-minute unit as well. See the message handler in createGateway.
 *
 * On this line /grid/live_grid_ws is not the only metered socket: /grid/ta_chart_ws is charged
 * the same way, with the same no-exemption rule, but on the OTHER leg. It is push-only --
 * live-grid reads no client frame from it, it re-runs build_series and pushes a figure or a
 * delta every TA_PUSH_INTERVAL_MS (default one a second) -- so the paid unit there is the
 * upstream PUSH, not a client frame, and the FIRST push is charged too: the build_series the
 * upgrade itself triggers is paid work like every later one. Metering the client's frames on
 * that socket would meter nothing at all: it sends none.
 */
const METERED_GRID = new Set(["/grid/live_grid", "/grid/symbol_meta", "/grid/series",
  "/grid/chart", "/grid/ta_chart"]);
/**
 * A hard ceiling per grid socket, for the whole 240s lifetime: validated CLIENT frames on
 * /grid/live_grid_ws, upstream PUSHES on /grid/ta_chart_ws -- whichever leg that socket's
 * paid work arrives on. It is NOT configurable and it is evaluated BEFORE either budget, so
 * it is what bounds a single socket first: no value of quoteDailyLimit can lengthen one, and
 * a tick-chart stream is therefore at most 60 pushes (~60 x TA_PUSH_INTERVAL_MS) before the
 * client must reconnect. The per-frame charges below
 * are the real accounting; this is the backstop, so that no accounting bug can turn one
 * admitted socket into an unbounded stream of upstream work.
 * 60 is generous for a human changing a watchlist and far below what a script can send.
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
const OPTIONAL_DOCS = new Set(["/grid/apps.json", "/grid/symbol_meta"]);
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
// Three upstreams at this tag (openbq-docker serves no /ai). /api/... -> openbq-api, plain HTTP
// on the bridge, behind the stack's Basic pair; the prefix is stripped ("/api/api/v1/x" ->
// "/api/v1/x") and the credential injected. /grid/... -> live-grid (the opt-in `live`
// profile), the same way and behind the SAME pair (below). /news/... -> rss-ticker, on the
// tailnet, no credential (it has none). Nothing the caller sent goes with any of them.
function target(path, config) {
  if (path.startsWith("/api/")) {
    return { url: new URL(path.slice(4), config.apiOrigin), options: {},
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
    return { url: new URL(path.slice(5), config.gridOrigin), options: {},
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

/** Bounded JSON-only request; never relay cookies, errors, redirects or credentials. */
export async function getJson(path, config, signal) {
  const { url, headers, options } = target(path, config);
  // The installed v11 catalogue is larger than v10's. Only this exact admitted
  // discovery path gets the larger finite response budget; callers cannot set it.
  const maxBody = config.apiUpstream === "v11" && path === "/api/widgets.json" ? 8 * 1024 * 1024 : MAX_BODY;
  const send = url.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, rejectPromise) => {
    const request = send(url, { ...options, method: "GET", headers, signal }, response => {
      if (response.statusCode !== 200 ||
          (response.headers["content-encoding"] && response.headers["content-encoding"] !== "identity") ||
          Number(response.headers["content-length"] ?? 0) > maxBody ||
          !/^application\/json(?:\s*;|$)/i.test(response.headers["content-type"] ?? "")) {
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
        if (size > maxBody) { response.destroy(); rejectPromise(new Error("Body limit")); }
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
  if (one && method === "DELETE" && SUBSCRIPTION_SYMBOL_RE.test(one[1])) {
    return { method, path: `/api/subscriptions/${one[1]}` };
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

async function sendTemporal(method, path, body, config, signal) {
  const url = new URL(path.slice("/temporal".length), config.temporalOrigin);
  const headers = { Authorization: config.temporalAuthorization, Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["Content-Length"] = String(Buffer.byteLength(body));
  }
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(url, { method, headers, signal }, response => {
      const ok = [200, 201, 202].includes(response.statusCode);
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
 * its own LIVE_GRID_PUBLIC_URL, which on this stack is the internal compose address
 * (docker-compose.yml). Relayed through /grid, the frame must open THIS door's page --
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

/** Test dependency injection is not exposed through environment variables. */
export function createGateway(config, { requestJson = getJson, openNews = connectNews,
  openGrid = connectGrid, sendSubscription = sendGrid, fetchPage = getGridPage,
  requestState = remoteState, now = Date.now, socketMs = 240000, firstFrameMs = 10000 } = {}) {
  let budget = config.requestsPerMinute, resetAt = now() + 60000, quoteCount = 0, day = Math.floor(now() / 86400000);
  let inflight = 0, sockets = 0;
  const stateCalls = new Set();
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
  // The Subscriptions page, fetched from live-grid once and kept: it is the one route served
  // before the lock (below), so an unauthenticated caller must cost no upstream dial and no
  // share of the per-minute budget. A failed fetch is not kept; the next request retries.
  let page = null;
  function subscriptionsPage() {
    if (!page) page = fetchPage(config, AbortSignal.timeout(10000)).catch(error => { page = null; throw error; });
    return page;
  }
  async function handleSubscriptions(req, res, route) {
    if (!config.gridOrigin) return reply(res, 503);
    // Before the vendor unit is charged, so a refusal for load never spends the day.
    if (inflight >= config.maxConcurrent) return reply(res, 429);
    let body;
    if (route.method === "POST") {
      const raw = await jsonBody(req, 1024);
      if (typeof raw === "number") return reply(res, raw);
      const symbol = JSON.parse(raw.toString("utf8"))?.symbol;
      if (typeof symbol !== "string" || !SUBSCRIPTION_SYMBOL_RE.test(symbol.trim())) {
        return reply(res, 422, { detail: SUBSCRIPTION_REFUSALS[422] });
      }
      // A new symbol is a new EODHD subscription: charged to the vendor day like a quote.
      if (!quoteAllowed()) return reply(res, 429);
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
      if (req.method === "GET" && req.url === SUBSCRIPTIONS_PAGE) {
        const pageUrl = requestUrl(req, config);
        if (!pageUrl) return reply(res, 421);
        if (req.headers["transfer-encoding"] ||
            (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
        if (!config.gridOrigin) return reply(res, 503);
        return replyPage(res, await subscriptionsPage());
      }
      // The lock precedes route discovery, health, Host and Origin validation.
      if (!authorized(req, config)) return reply(res, 401);
      const url = requestUrl(req, config);
      if (!url) return reply(res, 421);
      if (req.headers.origin && req.headers.origin !== config.origin) return reply(res, 403);
      if (url.pathname.startsWith("/state/")) {
        if (!spend(1)) return reply(res, 429);
        if (config.stateStorage !== "postgresql") return await handleState(req, res, url, config);
        const match = /^\/state\/(\d{1,20})(?:\/(.+))?$/.exec(url.pathname);
        if (!match || url.search || (match[2] !== undefined && !stateFile(match[2]))) return reply(res, 404);
        const [, id, name] = match;
        if (name === undefined ? req.method !== "GET" : !["PUT", "DELETE"].includes(req.method)) return reply(res, 405);
        if (inflight >= config.maxConcurrent) return reply(res, 429);
        inflight++;
        const controller = new AbortController(); stateCalls.add(controller);
        const abort = () => controller.abort();
        res.once("close", abort); req.once("aborted", abort);
        try {
          let body;
          if (req.method === "PUT") {
            body = await jsonBody(req, STATE_FILE_MAX);
            if (typeof body === "number") return reply(res, body);
          }
          const answer = await requestState(req.method, id, name, body, config,
            AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]));
          return reply(res, answer.status, answer.json);
        } finally {
          stateCalls.delete(controller); res.off("close", abort); req.off("aborted", abort); inflight--;
        }
      }
      if (url.pathname.startsWith("/grid/api/subscriptions")) {
        const route = subscriptionRoute(url, req.method);
        if (!route) return reply(res, 404);
        if (!spend(1)) return reply(res, 429);
        return await handleSubscriptions(req, res, route);
      }
      if (url.pathname.startsWith("/temporal/")) {
        const route = temporalRoute(url, req.method, config);
        if (!route) return reply(res, 404);
        if (!config.temporalOrigin || !config.temporalAuthorization) return reply(res, 503);
        if (!spend(1) || inflight >= config.maxConcurrent) return reply(res, 429);
        let body;
        if (req.method === "POST" || req.method === "PUT") {
          if (!/^application\/json(?:\s*;|$)/i.test(req.headers["content-type"] ?? "")) return reply(res, 415);
          body = await jsonBody(req, 1048576);
          if (typeof body === "number") return reply(res, body);
        } else if (req.headers["transfer-encoding"] || (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
        // Reading the body yields; another request may have taken the slot.
        if (inflight >= config.maxConcurrent) return reply(res, 429);
        inflight++;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 12000);
        const disconnect = () => { if (!res.writableEnded) controller.abort(); };
        res.once("close", disconnect);
        try {
          const answer = await sendTemporal(req.method, route.path, body, config, controller.signal);
          return reply(res, temporalStatus(answer.status), answer.json);
        } finally { clearTimeout(timer); res.off("close", disconnect); inflight--; }
      }
      if (req.method !== "GET" || req.headers["transfer-encoding"] ||
          (req.headers["content-length"] && req.headers["content-length"] !== "0")) return reply(res, 405);
      if (!spend(1)) return reply(res, 429);
      if (url.pathname === "/_gateway/health" && !url.search) return reply(res, 200, { ok: true });
      const path = upstreamPath(url, config);
      if (!path) return reply(res, 404);
      // live-grid is the opt-in `live` profile: until settings.json says it runs
      // ("liveGrid": true), every /grid route answers 503, as /news does without the wire.
      if (path.startsWith("/grid/") && !config.gridOrigin) return reply(res, 503);
      // The daily budget is a cap on VENDOR calls, wherever they are reached from. The two
      // manifests under /api/ are openbq-api's own static documents -- no provider is called
      // -- so they are not metered; the grid's data routes DO reach the vendor, from the
      // same counter (METERED_GRID above, and why that deviates from the donor's main).
      const vendor = path.startsWith("/api/api/v1/") || METERED_GRID.has(path.split("?")[0]);
      if (inflight >= config.maxConcurrent || (vendor && !quoteAllowed())) return reply(res, 429);
      inflight++;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      const disconnect = () => { if (!res.writableEnded) controller.abort(); };
      res.once("close", disconnect);
      try {
        const answer = await requestJson(path, config, controller.signal);
        reply(res, 200, path === "/grid/widgets.json" ? rewriteGridWidgets(answer, config) : answer);
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
    // THREE socket routes at this tag: the wire (Ep. 8), the quote grid (Ep. 10) and this
    // line's tick chart. policy.mjs' socketTarget holds the rule for all three -- the exact
    // path and no query for the first two, whose subscription is a frame, and the path plus
    // /grid/ta_chart's own validated query for the third, whose subscription IS the URL --
    // and it is the SAME function the web layer's ticket signer consults, so the two layers
    // can never drift about what may be opened. The target it returns is what gets dialled,
    // so the query that leaves is the one it re-serialised, never the caller's raw string.
    // A subprotocol is refused here: no upstream speaks one, and ws would otherwise have to
    // negotiate it. Anything unmatched is 404, before any upstream is consulted.
    const target = socketTarget(url.pathname + url.search, config.origin);
    if (req.method !== "GET" || !target || req.headers["sec-websocket-protocol"]) return reject(socket, 404);
    const ta = url.pathname === "/grid/ta_chart_ws";
    const grid = ta || url.pathname === "/grid/live_grid_ws";
    // Nothing to subscribe to: the operator has approved no feeds, so there is no socket to
    // open. 503, not 404 -- the route exists, the upstream is simply not configured, which
    // is what verify.mjs's own probe distinguishes. The grid has the same state here: on
    // openbq-docker live-grid is the opt-in `live` compose profile, so until settings.json
    // says it runs ("liveGrid": true, config.mjs) its sockets answer 503 as well.
    if (!grid && !Object.keys(config.feeds).length) return reject(socket, 503);
    if (grid && !config.gridOrigin) return reject(socket, 503);
    // Both caps are charged BEFORE handleUpgrade: a refusal must cost the same whether the
    // handshake would have succeeded or not, and an upgrade that is going to be refused must
    // never get as far as allocating a ws client. Six units, a socket's price, since a socket
    // occupies the door for as long as it is open.
    if (sockets >= config.maxSockets || !spend(6)) return reject(socket, 429);
    wss.handleUpgrade(req, socket, head, client => {
      sockets++;
      // The 10s handshake deadline set above must not go on applying to an open socket.
      socket.setTimeout(0);
      let upstream, subscribed = false, pending = null, frames = 0, pushes = 0;
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
      /**
       * Wiring the upstream leg is identical for all three sockets -- the same size and
       * back-pressure bounds on what it may push, the same teardown in both directions --
       * so it lives here once. Only WHEN it is opened differs: on the first validated
       * frame for the wire and the quote grid, at upgrade for the tick chart, which has no
       * client frame to wait for.
       */
      const connect = () => {
        try {
          upstream = grid ? openGrid(config, target.slice("/grid".length)) : openNews(config);
        } catch { close(); return false; }
        upstream.on("message", (message, isBinary) => {
          if (isBinary || message.length > MAX_SOCKET || client.readyState !== WebSocket.OPEN ||
              client.bufferedAmount > 262144) return close();
          // The tick chart's PUSHES are the paid work on that socket: each one re-runs
          // build_series through openbq-api's historical route (live-grid/app/main.py's
          // ta_chart_ws loop), once per TA_PUSH_INTERVAL_MS. So it is charged exactly the way
          // the quote grid's client frames are, on the leg where the work actually is, and
          // with the same NO-EXEMPTION rule: the FIRST push is charged too, because the
          // build_series the upgrade itself triggers is paid work like every later one, and
          // exempting it would let socket churn buy one free fetch per upgrade -- ten a
          // minute fit inside the shipped 60 rpm. The upgrade's six units buy the door's slot
          // and the per-minute budget for that first push, nothing from the vendor counter;
          // pushes after it cost one per-minute unit as well. FRAME_CAP bounds the stream
          // whatever the budgets allow, and is checked first. When anything refuses the relay
          // closes and the slot comes back -- there is no way to answer 429 on an open
          // socket, and a chart that silently stops updating is the blank-and-say-nothing
          // failure live-grid's own handler was fixed for.
          if (ta && (++pushes > FRAME_CAP || (pushes > 1 && !spend(1)) || !quoteAllowed())) {
            return close();
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
        // The tick chart takes no frame at all (see above); the wire takes exactly one.
        if (binary || ta || (!grid && subscribed)) return close();
        const frame = grid ? liveGridSubscription(data) : newsSubscription(data, config);
        if (!frame) return close();
        // NO grid frame is free, the first included (METERED_GRID above says why, and why the
        // REST cap is a half-measure without this). Every validated frame charges the daily
        // VENDOR counter once per symbol it asks live-grid to seed -- the very counter the
        // /api leg spends, so "the daily cap" means one thing on both legs.
        //
        // The first frame WAS exempt, on the reasoning that the upgrade's six units had
        // bought it. That was wrong, and the hole was socket CHURN rather than frames within
        // one socket: at the shipped 60 requests a minute an upgrade costs six, so a client
        // could open ten sockets a minute and get ten free first frames of up to ~40 symbols
        // each (SYMBOL_LIST_RE is 240 characters) -- on the order of 400 paid EODHD seeds a
        // minute with quoteCount never incremented, indefinitely, since live-grid seeds a
        // symbol once per process lifetime and rotating the universe keeps every call paid.
        // So the six units buy the door's own slot and the PER-MINUTE budget for that first
        // frame; they buy nothing from the vendor counter.
        //
        // Either refusal closes the relay, the same way a frame outside the contract does:
        // the door has no way to answer 429 on an open socket, and a silently dropped frame
        // would leave the client believing a watchlist it is not being sent. FRAME_CAP is
        // checked first and independently -- a cap that only bites when a budget is tight
        // would not be a backstop.
        if (++frames > FRAME_CAP) return close();
        if (grid) {
          // The per-minute unit is what the upgrade already paid for the first frame; every
          // frame after it costs one more.
          if (frames > 1 && !spend(1)) return close();
          // The rebuilt frame, not the caller's bytes: this is the list that will reach
          // live-grid, so it is the list that is charged for.
          const symbols = JSON.parse(frame).params.symbol.split(",").length;
          for (let i = 0; i < symbols; i++) if (!quoteAllowed()) return close();
        }
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
        // a grid client legitimately sends a params frame per parameter change for the
        // socket's whole 240s lifetime, and a live-grid that is not draining would otherwise
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
    for (const controller of stateCalls) controller.abort();
    for (const client of wss.clients) client.terminate();
    server.closeAllConnections();
    return new Promise(resolve => server.close(resolve));
  };
  return server;
}
