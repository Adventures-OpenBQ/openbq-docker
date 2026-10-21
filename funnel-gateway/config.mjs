// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { validSsrmRoutes } from "./policy.mjs";
import { RITA_MODEL_RE } from "./rita-policy.mjs";
import { readFileSync } from "node:fs";
import { isIP } from "node:net";
import { isAbsolute, normalize } from "node:path";

// The door is the stack node's Funnel port 10000: the node's :443 stays openbq-api and :8443
// the episode 3 reference, both for the tailnet, and Funnel offers only 443, 8443 and 10000.
// A portless origin is still accepted
// for a reader who publishes a dedicated node's :443 instead. `allowedPort` names the one
// port an origin may carry (the wire's is 8088). `tailnet` is false only for previewOrigin,
// the web preview's own (Vercel) origin, which is not on the tailnet and is portless
// (allowedPort null: no port at all).
function httpsOrigin(value, tailnet = true, allowedPort = "10000") {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== allowedPort) ||
      url.pathname !== "/" || url.search || url.hash ||
      (tailnet && !/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(url.hostname))) {
    throw new Error("Invalid HTTPS origin");
  }
  return url.origin;
}

// A tailnet IPv4 address (the CGNAT /10 Tailscale assigns from). The wire's address is dialled directly
// rather than trusting whatever DNS this container has.
function tailnetAddress(value) {
  const parts = String(value).split(".").map(Number);
  return isIP(value ?? "") === 4 && parts[0] === 100 && parts[1] >= 64 && parts[1] <= 127;
}

// Every key a settings file may carry at this tag. A key from a later line (tickUrl...) is
// refused rather than ignored: a stack at this tag has no such upstream, and a silently
// ignored setting is how an operator believes a door is configured when it is not.
// Rita's old tailnet settings (ritaOrigin, ritaAddress, socksProxy) are refused: since
// 2026-10-20 the door's Rita is the openbq-rita-door compose service, switched on by "rita".
// `gridOrigin` is deliberately NOT a key: like apiOrigin it is a fixed compose service name
// (see the bottom of validateConfig), never a setting. `liveGrid` (openbq-docker v10) is the
// one switch: live-grid is the opt-in `live` compose profile here, so the door must be told
// it runs, and /grid answers 503 until it is.
const SETTINGS_KEYS = new Set(["origin", "previewOrigin", "stateDir", "maxConcurrent", "maxSockets", "rssOrigin", "rssAddress", "feeds", "liveGrid", "tableService", "tableDesktopPrincipal", "ssrmRoutes", "tableTimeoutMs", "ssrmTimeoutMs", "rita", "ritaModel", "ritaPerHour", "mcp", "mcpPerHour"]);

// lanes/ssrm_widgets.json as door paths: the image copies it to /lanes beside /app (Dockerfile).
const DEFAULT_SSRM_ROUTES = JSON.parse(readFileSync(new URL("../lanes/ssrm_widgets.json", import.meta.url), "utf8"))
  .map(w => `/api${w.route}/ssrm`);

function bounded(value, label) {
  if (!Number.isInteger(value) || value < 1 || value > 32) throw new Error(`${label} must be between 1 and 32`);
  return value;
}

// The daily vendor cap and the per-minute request budget were removed (user ruling 2026-10-17).
// A settings file that still names them is refused by name, so the operator deletes them knowingly.
const REMOVED_KEYS = new Set(["quoteDailyLimit", "requestsPerMinute"]);

export function validateConfig(settings, secrets) {
  for (const key of Object.keys(settings)) {
    if (REMOVED_KEYS.has(key)) throw new Error(`Removed setting: ${key} (the gateway no longer has this budget; delete it)`);
    if (!SETTINGS_KEYS.has(key)) throw new Error(`Unknown setting: ${key}`);
  }
  const origin = httpsOrigin(settings.origin, true);
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(secrets.token ?? "") ||
      typeof secrets.apiUsername !== "string" || !/^[A-Za-z0-9_.@-]{1,128}$/.test(secrets.apiUsername) ||
      typeof secrets.apiPassword !== "string" || !secrets.apiPassword.length ||
      /[\r\n\0]/.test(secrets.apiPassword) || secrets.apiPassword.length > 1024) {
    throw new Error("Invalid machine or API credential");
  }
  const maxConcurrent = bounded(settings.maxConcurrent ?? 8, "Max concurrent");
  const maxSockets = bounded(settings.maxSockets ?? 4, "Max sockets");
  // The web preview's own origin. Naming it turns on socket tickets (server.mjs): the one
  // Origin, besides the gateway's own, a WebSocket may arrive from. Unset = off.
  const previewOrigin = settings.previewOrigin === undefined ? null : httpsOrigin(settings.previewOrigin, false, null);
  // Where the web preview's per-user configuration is kept (server.mjs /state). A
  // writable directory mounted into this otherwise read-only container. Unset = off.
  const stateDir = settings.stateDir === undefined ? null : settings.stateDir;
  if (stateDir !== null && (typeof stateDir !== "string" || !isAbsolute(stateDir) || normalize(stateDir) !== stateDir)) {
    throw new Error("State directory must be a normalized absolute path");
  }
  // The wire: rss-ticker, reached by a tailnet HTTPS name for SNI and the certificate,
  // dialled at a pinned tailnet address. Both or neither; neither = the
  // /news family is off. Its port is :8088, the one ts-config/serve*.json publishes rss-ticker
  // on (a portless origin stays valid for a reader who fronts the pool on a node's own :443).
  if ((settings.rssOrigin === undefined) !== (settings.rssAddress === undefined)) {
    throw new Error("RSS origin and address: set both or neither");
  }
  const rssOrigin = settings.rssOrigin === undefined ? null : httpsOrigin(settings.rssOrigin, true, "8088");
  if (rssOrigin && !tailnetAddress(settings.rssAddress)) throw new Error("RSS address must be a tailnet IPv4 address");
  const rssAddress = rssOrigin ? settings.rssAddress : null;
  // The approved feeds: `{ "<https feed url>": <rss-ticker feed id> }`. The ONLY feeds the
  // door will ever name -- the url side gates the socket's subscription frame, the id side
  // gates /news/api/news -- so the gateway has no route through which a caller can make the
  // pool fetch a URL nobody approved. Empty (the default) = the /news family is off: every
  // feed_id is unapproved, so the history route 404s, and the socket answers 503.
  const feeds = settings.feeds === undefined ? {} : settings.feeds;
  if (!feeds || Array.isArray(feeds) || typeof feeds !== "object" || Object.keys(feeds).length > 50) {
    throw new Error("Invalid feed map");
  }
  // The map is a bijection: one approved URL, one rss-ticker id. Two URLs sharing an id
  // would make the two halves of the contract disagree -- /news/api/news would serve one
  // feed's history under the other's approval -- so a duplicate is a misconfiguration, not
  // a preference. `new URL` is wrapped so a malformed entry fails with this block's own
  // message rather than the platform's bare "Invalid URL".
  const ids = new Set();
  for (const [feed, id] of Object.entries(feeds)) {
    let url; try { url = new URL(feed); } catch { throw new Error("Invalid approved feed"); }
    if (url.protocol !== "https:" || url.username || url.password || url.hash ||
        !Number.isSafeInteger(id) || id < 1) throw new Error("Invalid approved feed");
    if (ids.has(id)) throw new Error("Invalid approved feed: two feeds share one id");
    ids.add(id);
  }
  // Approved feeds with nowhere to send them is a misconfiguration, not a degraded mode:
  // refuse at startup rather than 404/502 per request once the door is already open.
  if (Object.keys(feeds).length && !rssOrigin) throw new Error("Approved feeds need an RSS origin and address");
  // live-grid (the `live` profile) is on only when the operator says it runs. A boolean and
  // nothing else: its origin is never a setting (gridOrigin below).
  const liveGrid = settings.liveGrid === undefined ? false : settings.liveGrid;
  if (typeof liveGrid !== "boolean") throw new Error("liveGrid must be true or false");
  // Rita (rita-policy.mjs): off unless "rita" is true, and then only with the model the
  // door forces on every query. ritaPerHour bounds each user's queries (one per tool round).
  const rita = settings.rita ?? false;
  if (typeof rita !== "boolean") throw new Error("rita must be true or false");
  if (!rita && (settings.ritaModel !== undefined || settings.ritaPerHour !== undefined)) throw new Error("Rita settings need rita: true");
  if (rita && !RITA_MODEL_RE.test(settings.ritaModel ?? "")) throw new Error("ritaModel must name an openai: model");
  const ritaPerHour = settings.ritaPerHour ?? 120;
  if (!Number.isInteger(ritaPerHour) || ritaPerHour < 1 || ritaPerHour > 10000) throw new Error("Invalid ritaPerHour");
  // openbq-mcp (mcp-policy.mjs): off unless "mcp" is true. mcpPerHour bounds each user's messages.
  const mcp = settings.mcp ?? false;
  if (typeof mcp !== "boolean") throw new Error("mcp must be true or false");
  if (!mcp && settings.mcpPerHour !== undefined) throw new Error("MCP settings need mcp: true");
  const mcpPerHour = settings.mcpPerHour ?? 600;
  if (!Number.isInteger(mcpPerHour) || mcpPerHour < 1 || mcpPerHour > 100000) throw new Error("Invalid mcpPerHour");
  const tableTimeoutMs = settings.tableTimeoutMs ?? 65000;
  if (!Number.isInteger(tableTimeoutMs) || tableTimeoutMs < 1000 || tableTimeoutMs > 65000) throw new Error("Invalid table timeout");
  // An SSRM first page acquires the widget's whole result (od's lane deadline 165 s, its
  // SSRM deadline 300 s), so it gets its own limit, up to od's; managed routes keep theirs.
  const ssrmTimeoutMs = settings.ssrmTimeoutMs ?? 170000;
  if (!Number.isInteger(ssrmTimeoutMs) || ssrmTimeoutMs < 1000 || ssrmTimeoutMs > 300000) throw new Error("Invalid SSRM timeout");
  const tableService = settings.tableService ?? false;
  const tableDesktopPrincipal = settings.tableDesktopPrincipal ?? null;
  // Unset = the 23 routes od serves (lanes/ssrm_widgets.json as door paths).
  const ssrmRoutes = settings.ssrmRoutes ?? DEFAULT_SSRM_ROUTES;
  if (typeof tableService !== "boolean" || !validSsrmRoutes(ssrmRoutes)) throw new Error("Invalid table settings");
  if (tableDesktopPrincipal !== null && !/^desktop:[A-Za-z0-9_-]{1,100}$/.test(tableDesktopPrincipal)) throw new Error("Invalid desktop table principal");
  const credential = value => typeof value === "string" && /^[A-Za-z0-9_-]{32,256}$/.test(value);
  if (tableService && !credential(secrets.tableGatewayToken)) throw new Error("Table gateway credential required");
  if (secrets.tableRelayToken !== undefined && !credential(secrets.tableRelayToken)) throw new Error("Invalid table relay credential");
  const privateTokens = [secrets.token, secrets.tableGatewayToken, secrets.tableRelayToken].filter(Boolean);
  if (new Set(privateTokens).size !== privateTokens.length) throw new Error("Table credentials must be distinct");
  return {
    tableOrigin: tableService ? "http://table-service:8080" : null,
    tableGatewayToken: secrets.tableGatewayToken, tableRelayToken: secrets.tableRelayToken,
    tableDesktopPrincipal, ssrmRoutes, tableTimeoutMs, ssrmTimeoutMs,
    origin, previewOrigin, maxConcurrent, maxSockets, stateDir,
    rssOrigin, rssAddress, feeds,
    token: secrets.token,
    apiAuthorization: "Basic " + Buffer.from(`${secrets.apiUsername}:${secrets.apiPassword}`).toString("base64"),
    // Never accept a caller-supplied upstream or a configurable generic proxy.
    apiOrigin: "http://openbq-api:6900",
    // live-grid (v10; ported from bdobb-dev/openbb-docker e8c1239): a sibling on the same
    // openbq-internal bridge, so a fixed service name for the same reason apiOrigin is --
    // not something a setting or a caller can point elsewhere. It sits behind the same Basic
    // pair as openbq-api (apiAuthorization above). Admission from the OUTSIDE is unchanged --
    // this gateway's Bearer token plus the reviewed /grid/ route set in policy.mjs; the pair
    // is only what the gateway then presents on the bridge. The compose SERVICE name
    // (live-grid), since this compose file sets no container_name. null = the `live` profile
    // is not running ("liveGrid" unset or false): every /grid route and socket answers 503.
    gridOrigin: liveGrid ? "http://live-grid:6903" : null,
    // The Episode 3 reference (the episode3-demo service, network alias openbq-reference):
    // a keyless local fixture on the same bridge, so a fixed service name like apiOrigin,
    // never a setting, and NO credential is presented on the bridge.
    refOrigin: "http://openbq-reference:17783",
    // The door's own Rita: a fixed compose service holding no paid provider key. null = off.
    ritaUpstream: rita ? "http://openbq-rita-door:7778" : null,
    ritaModel: rita ? settings.ritaModel : null, ritaPerHour,
    // The stack's openbq-mcp, on openbq-internal (docker-compose.v6.yml). null = off.
    mcpUpstream: mcp ? "http://openbq-mcp:6901" : null, mcpPerHour,
  };
}

/**
 * Settings are a JSON file on a read-only bind mount; the three secrets come from
 * gateway.env (compose `env_file`): the machine token, and the API's Basic pair -- the same
 * OPENBB_API_USERNAME/OPENBB_API_PASSWORD credentials.env gives openbq-api, repeated here so
 * the gateway never loads the provider keys credentials.env also holds.
 */
export function readConfig(directory = "/run/bdobb", env = process.env) {
  return validateConfig(
    JSON.parse(readFileSync(`${directory}/settings.json`, "utf8")),
    { token: env.GATEWAY_TOKEN, apiUsername: env.OPENBB_API_USERNAME, apiPassword: env.OPENBB_API_PASSWORD,
      tableGatewayToken: env.TABLE_GATEWAY_TOKEN, tableRelayToken: env.TABLE_RELAY_TOKEN },
  );
}
