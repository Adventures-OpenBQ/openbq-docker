// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

// openbq-docker v3.0.0. Brought down from openbq-docker v8.0.0 (itself ported from
// bdobb-dev/openbb-docker v8.0.3, 775354f, without /ai) minus the /news wire, which stays
// at v8, and without PR #10's managed-table routes.

import { createServer, request as httpRequest } from "node:http";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { upstreamPath, stateFile } from "./policy.mjs";

const MAX_BODY = 2 * 1024 * 1024;
/**
 * The packaged desktop app's webview origins (V10-P1, user ruling 2026-10-15). Tauri's http
 * plugin stamps one of these on every request it makes (tauri://localhost on macOS, iOS and
 * Linux; http://tauri.localhost on Windows and Android), and the webview's own WebSocket
 * carries the same one. An Origin is never a credential: these pass the Origin rule only
 * behind the Bearer lock, on HTTP. (Its HTTP half moved down with the gateway; the socket
 * ticket for the webview's own socket, /grid/ws_ticket, arrives at v10.)
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
function reply(res, code, value = { error: "Request refused" }) {
  if (value instanceof SvgBody) {
    // The logo: same common headers, its own type, and a sandbox CSP so a directly opened SVG runs nothing.
    res.writeHead(code, { ...COMMON, "Content-Type": "image/svg+xml",
      "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'" });
    return res.end(value.text);
  }
  res.writeHead(code, { ...COMMON, "Content-Type": "application/json" });
  res.end(JSON.stringify(value));
}
const COMMON = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
};
function reject(socket, code) {
  socket.end(`HTTP/1.1 ${code} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}
// Two upstreams: /api/... -> openbq-api, plain HTTP on the bridge, behind the stack's Basic
// pair; the prefix is stripped ("/api/api/v1/x" -> "/api/v1/x") and the credential injected.
// /ref/... -> the keyless reference fixture, "/ref" stripped, NO Authorization header.
// Nothing the caller sent goes with either.
const LOGO = "/ref/assets/bdobb-logo.svg", MAX_SVG = 262144;
// The upstream URL is built by concatenation, never by resolving the path against the origin,
// so the host can only ever be the fixed origin (a "//host" path would otherwise replace it).
function target(path, config) {
  if (path.startsWith("/api/")) {
    return { url: new URL(config.apiOrigin + path.slice(4)),
      headers: { Authorization: config.apiAuthorization, Accept: "application/json" } };
  }
  return { url: new URL(config.refOrigin + path.slice(4)),
    headers: { Accept: path === LOGO ? "image/svg+xml" : "application/json" } };
}
/** The reference logo's bytes: the one non-JSON body the door relays. */
class SvgBody { constructor(text) { this.text = text; } }

/** Bounded JSON-only request (plus the one SVG logo); never relay cookies, errors, redirects or credentials. */
export async function getJson(path, config, signal) {
  const { url, headers } = target(path, config);
  const svg = path === LOGO, limit = svg ? MAX_SVG : MAX_BODY;
  return new Promise((resolve, rejectPromise) => {
    const request = httpRequest(url, { method: "GET", headers, signal }, response => {
      if (response.statusCode !== 200 ||
          !(svg ? /^image\/svg\+xml(?:\s*;|$)/i : /^application\/json(?:\s*;|$)/i).test(response.headers["content-type"] ?? "")) {
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

/** Test dependency injection is not exposed through environment variables. */
export function createGateway(config, { requestJson = getJson, now = Date.now } = {}) {
  let budget = config.requestsPerMinute, resetAt = now() + 60000, quoteCount = 0, day = Math.floor(now() / 86400000);
  let inflight = 0;
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
  // No socket route at this tag: the first (/news/ws/news) arrives with the wire at v8.
  // An upgrade is refused after the same lock, so it never tells a caller more than HTTP does.
  server.on("upgrade", (req, socket) => {
    socket.on("error", () => {});
    reject(socket, authorized(req, config) ? 404 : 401);
  });
  server.closeGateway = () => {
    server.closeAllConnections();
    return new Promise(resolve => server.close(resolve));
  };
  return server;
}
