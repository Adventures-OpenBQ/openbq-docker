// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { request } from "node:http";
import { pathToFileURL } from "node:url";
import { readConfig } from "./config.mjs";

/**
 * The preflight before the door opens: openbq-api, reached on the bridge with the stack's
 * Basic pair, must answer 422 to a symbol-less quote -- credentials accepted, validation
 * reached, no provider called. 401 means the pair is wrong. The same request WITHOUT the pair
 * must answer 401: anything else means the API's lock (OPENBB_API_AUTH in credentials.env) is
 * OFF, which is the one state in which this door must not open (lock first, then door).
 * openbq-docker serves no /ai, so there is no Rita leg, and the wire's leg arrives with
 * the wire at v8.
 */
export async function checkUpstreams(config) {
  const quote = headers => new Promise((resolve, reject) => {
    const req = request(new URL("/api/v1/equity/price/quote", config.apiOrigin), {
      headers, signal: AbortSignal.timeout(10000),
    }, res => { res.destroy(); resolve(res.statusCode); });
    req.on("error", reject); req.end();
  });
  const code = await quote({ Authorization: config.apiAuthorization });
  if (code !== 422) throw new Error(`API auth preflight failed (HTTP ${code})`);
  const open = await quote({});
  if (open !== 401) throw new Error(`API lock preflight failed: no credential answered HTTP ${open}, wanted 401`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await checkUpstreams(readConfig());
    console.log("PASS: openbq-api authenticates the stack pair and is locked. No quote requested.");
  } catch (error) { console.error(`STOP: ${error.message}; no public route should be opened.`); process.exitCode = 1; }
}
