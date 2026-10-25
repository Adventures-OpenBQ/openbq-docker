// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { request } from "node:http";
import { pathToFileURL } from "node:url";
import { readConfig } from "./config.mjs";
import { getJson, connectNews, getRitaAgents } from "./server.mjs";

/**
 * The preflight before the door opens: openbq-api, reached on the bridge with the stack's
 * Basic pair, must answer 422 to a symbol-less quote (QUOTE_PROBES below) -- credentials
 * accepted, validation reached, no provider called. 401 means the pair is wrong. The same
 * request WITHOUT the pair must answer 401: anything else means the API's lock
 * (OPENBB_API_AUTH in credentials.env) is OFF, which is the one state in which this door
 * must not open (lock first, then door).
 * When live-grid is on ("liveGrid": true, the `live` profile), it must answer /health WITH the
 * same pair, and 401 without it (its lock, like the API's): it appends BasicAuthMiddleware to its whole app (live-grid/app/auth.py, reading
 * the credentials.env compose loads into it), so /health is behind auth like every other path
 * of its. /health stays authenticated deliberately: it reports feed status and tick-store
 * stats. When Rita is on ("rita": true), openbq-rita-door must answer agents.json offering no
 * paid model (checkRita below). When the wire is
 * configured, rss-ticker must answer both of the shapes the /news family relays: one page of
 * history for an APPROVED feed, and a socket handshake. The handshake is a handshake only --
 * no subscription frame is ever sent, so no feed is polled and no article body is fetched.
 */
// openbq-api (OpenBB Platform 5.0) mounts EODHD only as a core extension, under
// /api/v1/eodhd/, and has no standard /equity router; a stack that does carry the standard
// route still answers on it. The first path that is not a 404 is the one probed.
export const QUOTE_PROBES = ["/api/v1/eodhd/equity/price/quote", "/api/v1/equity/price/quote"];

/**
 * The door's Rita must answer her document, and every model it offers must be the Spark's
 * (openai:) or Ollama's (local, always registered by agent-rita): she lists a provider's models
 * only when its key is set, so an anthropic:, openrouter: or groq: option means a paid key
 * reached openbq-rita-door -- the second layer behind the door's forced model is gone.
 * It cannot see WHERE openai: points (agent-rita lists the same openai: models either way);
 * that is openbq-rita-door's own start check (docker-compose.v6.yml), which refuses an unset
 * or api.openai.com OPENAI_BASE_URL.
 */
export async function checkRita(config) {
  const doc = await getRitaAgents(config, AbortSignal.timeout(10000));
  if (typeof doc !== "object" || doc === null || !Object.keys(doc).length) throw new Error("Rita preflight failed: no agents");
  const paid = Object.values(doc).flatMap(agent => agent?.features?.model?.options ?? [])
    .map(option => option?.value).filter(value => typeof value !== "string" || !/^(openai|ollama):/.test(value));
  if (paid.length) throw new Error(`Rita preflight failed: openbq-rita-door offers paid models (${paid.join(", ")})`);
}

/** openbq-mcp must answer an initialize with a session: the leg /mcp depends on, and nothing more. */
export async function checkMcp(config) {
  const response = await fetch(new URL("/mcp", config.mcpUpstream), { method: "POST", signal: AbortSignal.timeout(10000),
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "check-upstreams", version: "1" } } }) });
  await response.body?.cancel();
  if (response.status !== 200 || !response.headers.get("mcp-session-id")) throw new Error(`MCP preflight failed (HTTP ${response.status})`);
}

export async function checkUpstreams(config) {
  const quote = (path, headers) => new Promise((resolve, reject) => {
    const req = request(new URL(path, config.apiOrigin), {
      headers, signal: AbortSignal.timeout(10000),
    }, res => { res.destroy(); resolve(res.statusCode); });
    req.on("error", reject); req.end();
  });
  let path, code;
  for (path of QUOTE_PROBES) {
    code = await quote(path, { Authorization: config.apiAuthorization });
    if (code !== 404) break;
  }
  if (code !== 422) throw new Error(`API auth preflight failed (HTTP ${code} on ${path})`);
  const open = await quote(path, {});
  if (open !== 401) throw new Error(`API lock preflight failed: no credential answered HTTP ${open}, wanted 401`);
  // Not getJson: that routes through target() and would prove the /grid prefix logic rather
  // than live-grid's own reachability, and /health is not a route this door forwards at all.
  // A raw dial to gridOrigin with the pair is exactly what the socket and the REST branch do
  // on the bridge, so this proves the leg they both depend on and nothing more.
  if (config.gridOrigin) {
    const health = headers => new Promise((resolve, reject) => {
      const req = request(new URL("/health", config.gridOrigin), {
        headers, signal: AbortSignal.timeout(10000),
      }, res => { res.destroy(); resolve(res.statusCode); });
      req.on("error", reject); req.end();
    });
    const gridCode = await health({ Authorization: config.apiAuthorization });
    if (gridCode !== 200) throw new Error(`live-grid preflight failed (HTTP ${gridCode})`);
    // The same request WITHOUT the pair must be 401 (D26): live-grid's lock is off unless
    // OPENBB_API_AUTH is true, and an open live-grid is the API's case again -- lock first.
    const gridOpen = await health({});
    if (gridOpen !== 401) {
      throw new Error(`live-grid lock preflight failed: no credential answered HTTP ${gridOpen}, wanted 401`);
    }
  }
  if (config.ritaUpstream) await checkRita(config);
  if (config.mcpUpstream) await checkMcp(config);
  // The first approved feed stands in for the whole map: what is being proved is that the
  // pinned dial, the certificate and the pool itself work, not that every feed has articles.
  const feed = Object.values(config.feeds)[0];
  if (feed) {
    await getJson(`/news/api/news?feed_id=${feed}&limit=1`, config, AbortSignal.timeout(10000));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("RSS socket preflight timed out")), 10000);
      const ws = connectNews(config);
      const settle = (error) => { clearTimeout(timer); ws.terminate(); error ? reject(error) : resolve(); };
      ws.once("error", settle);
      ws.once("open", () => settle());
    });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await checkUpstreams(readConfig());
    console.log("PASS: openbq-api authenticates the stack pair and is locked; live-grid answers /health behind that pair and is locked; the door's Rita offers no paid model; openbq-mcp opens a session; the wire's history/socket answer, each if configured. No quote or feed subscription requested.");
  } catch (error) { console.error(`STOP: ${error.message}; no public route should be opened.`); process.exitCode = 1; }
}
