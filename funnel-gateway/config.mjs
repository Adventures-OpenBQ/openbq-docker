// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from "node:fs";
import { isAbsolute, normalize } from "node:path";

// The door is the stack node's Funnel port 10000: the node's :443 stays openbq-api and :8443
// the episode 3 reference, both for the tailnet, and Funnel offers only 443, 8443 and 10000.
// A portless origin is still accepted
// for a reader who publishes a dedicated node's :443 instead.
function httpsOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "10000") ||
      url.pathname !== "/" || url.search || url.hash ||
      !/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(url.hostname)) {
    throw new Error("Invalid HTTPS origin");
  }
  return url.origin;
}

// Every key a settings file may carry at this tag. A key from a later line (the wire's
// rssOrigin/rssAddress/feeds and the socket keys previewOrigin/maxSockets at v8, liveGrid
// at v10) is refused rather than ignored: a stack at this tag has no such upstream, and a
// silently ignored setting is how an operator believes a door is configured when it is not.
// openbq-docker serves no /ai (Rita), so ritaOrigin, ritaAddress and socksProxy are refused too.
const SETTINGS_KEYS = new Set(["origin", "stateDir", "quoteDailyLimit",
  "requestsPerMinute", "maxConcurrent"]);

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
  // Where the web preview's per-user configuration is kept (server.mjs /state). A
  // writable directory mounted into this otherwise read-only container. Unset = off.
  const stateDir = settings.stateDir === undefined ? null : settings.stateDir;
  if (stateDir !== null && (typeof stateDir !== "string" || !isAbsolute(stateDir) || normalize(stateDir) !== stateDir)) {
    throw new Error("State directory must be a normalized absolute path");
  }
  return {
    origin, quoteDailyLimit, requestsPerMinute, maxConcurrent, stateDir,
    token: secrets.token,
    apiAuthorization: "Basic " + Buffer.from(`${secrets.apiUsername}:${secrets.apiPassword}`).toString("base64"),
    // Never accept a caller-supplied upstream or a configurable generic proxy.
    apiOrigin: "http://openbq-api:6900",
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
    { token: env.GATEWAY_TOKEN, apiUsername: env.OPENBB_API_USERNAME, apiPassword: env.OPENBB_API_PASSWORD },
  );
}
