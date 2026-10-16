// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { validSsrmRoutes } from "./policy.mjs";
import { readFileSync } from "node:fs";
import { isAbsolute, normalize } from "node:path";

// The door is the stack node's Funnel port 10000: the node's :443 stays openbq-api and :8443
// the episode 3 reference, both for the tailnet, and Funnel offers only 443, 8443 and 10000.
// A portless origin is still accepted
// for a reader who publishes a dedicated node's :443 instead. `tailnet` is false only for
// previewOrigin, the web preview's own (Vercel) origin, which is not on the tailnet and is
// portless (allowedPort null: no port at all).
function httpsOrigin(value, tailnet = true, allowedPort = "10000") {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== allowedPort) ||
      url.pathname !== "/" || url.search || url.hash ||
      (tailnet && !/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(url.hostname))) {
    throw new Error("Invalid HTTPS origin");
  }
  return url.origin;
}

// Every key a settings file may carry at this tag. A key from a later line (the wire's
// rssOrigin/rssAddress/feeds at v8, liveGrid at v10) is refused rather than ignored: a stack at this tag has no such upstream, and a
// silently ignored setting is how an operator believes a door is configured when it is not.
// openbq-docker serves no /ai (Rita), so ritaOrigin, ritaAddress and socksProxy are refused too.
const SETTINGS_KEYS = new Set(["origin", "previewOrigin", "stateDir", "quoteDailyLimit",
  "requestsPerMinute", "maxConcurrent", "maxSockets", "tableService", "tableDesktopPrincipal", "ssrmRoutes", "tableTimeoutMs", "ssrmTimeoutMs"]);

const DEFAULT_SSRM_ROUTES = JSON.parse(readFileSync(new URL("./ssrm-routes.json", import.meta.url), "utf8"));

export function validateConfig(settings, secrets) {
  for (const key of Object.keys(settings)) if (!SETTINGS_KEYS.has(key)) throw new Error(`Unknown setting: ${key}`);
  const origin = httpsOrigin(settings.origin);
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(secrets.token ?? "") ||
      typeof secrets.apiUsername !== "string" || !/^[A-Za-z0-9_.@-]{1,128}$/.test(secrets.apiUsername) ||
      typeof secrets.apiPassword !== "string" || !secrets.apiPassword.length ||
      /[\r\n\0]/.test(secrets.apiPassword) || secrets.apiPassword.length > 1024) {
    throw new Error("Invalid machine or API credential");
  }
  const quoteDailyLimit = settings.quoteDailyLimit ?? 100;
  if (!Number.isInteger(quoteDailyLimit) || quoteDailyLimit < 1 || quoteDailyLimit > 10000) {
    throw new Error("Quote daily limit must be between 1 and 10000");
  }
  // The per-minute budget and the concurrency cap were hard-coded (60 and 8) while the
  // preview served one quote card. They stay bounded: the gateway sits on a public Funnel.
  const requestsPerMinute = settings.requestsPerMinute ?? 60;
  if (!Number.isInteger(requestsPerMinute) || requestsPerMinute < 1 || requestsPerMinute > 600) {
    throw new Error("Requests per minute must be between 1 and 600");
  }
  const maxConcurrent = settings.maxConcurrent ?? 8;
  if (!Number.isInteger(maxConcurrent) || maxConcurrent < 1 || maxConcurrent > 32) {
    throw new Error("Max concurrent must be between 1 and 32");
  }
  const maxSockets = settings.maxSockets ?? 4;
  if (!Number.isInteger(maxSockets) || maxSockets < 1 || maxSockets > 32) {
    throw new Error("Max sockets must be between 1 and 32");
  }
  // The web preview's own origin. Naming it turns on socket tickets (server.mjs): the one
  // Origin, besides the gateway's own, a WebSocket may arrive from. Unset = off.
  const previewOrigin = settings.previewOrigin === undefined ? null : httpsOrigin(settings.previewOrigin, false, null);
  // Where the web preview's per-user configuration is kept (server.mjs /state). A
  // writable directory mounted into this otherwise read-only container. Unset = off.
  const stateDir = settings.stateDir === undefined ? null : settings.stateDir;
  if (stateDir !== null && (typeof stateDir !== "string" || !isAbsolute(stateDir) || normalize(stateDir) !== stateDir)) {
    throw new Error("State directory must be a normalized absolute path");
  }
  const tableTimeoutMs = settings.tableTimeoutMs ?? 65000;
  if (!Number.isInteger(tableTimeoutMs) || tableTimeoutMs < 1000 || tableTimeoutMs > 65000) throw new Error("Invalid table timeout");
  // An SSRM first page acquires the widget's whole result (od's lane deadline 165 s, its
  // SSRM deadline 300 s), so it gets its own limit, up to od's; managed routes keep theirs.
  const ssrmTimeoutMs = settings.ssrmTimeoutMs ?? 170000;
  if (!Number.isInteger(ssrmTimeoutMs) || ssrmTimeoutMs < 1000 || ssrmTimeoutMs > 300000) throw new Error("Invalid SSRM timeout");
  const tableService = settings.tableService ?? false;
  const tableDesktopPrincipal = settings.tableDesktopPrincipal ?? null;
  // Unset = the 23 routes od serves (ssrm-routes.json, lanes/ssrm_widgets.json as door paths).
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
    origin, previewOrigin, quoteDailyLimit, requestsPerMinute, maxConcurrent, maxSockets, stateDir,
    token: secrets.token,
    apiAuthorization: "Basic " + Buffer.from(`${secrets.apiUsername}:${secrets.apiPassword}`).toString("base64"),
    // Never accept a caller-supplied upstream or a configurable generic proxy.
    apiOrigin: "http://openbq-api:6900",
    // The Episode 3 reference (the episode3-demo service, network alias openbq-reference):
    // a keyless local fixture on the same bridge, so a fixed service name like apiOrigin,
    // never a setting, and NO credential is presented on the bridge.
    refOrigin: "http://openbq-reference:17783",
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
