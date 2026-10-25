// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { request } from "node:http";
import { pathToFileURL } from "node:url";
import { readConfig } from "./config.mjs";
import { getJson, connectNews } from "./server.mjs";

/**
 * The preflight before the door opens: openbq-api, reached on the bridge with the stack's
 * Basic pair, must answer 422 to a symbol-less quote -- credentials accepted, validation
 * reached, no provider called. 401 means the pair is wrong. The same request WITHOUT the pair
 * must answer 401: anything else means the API's lock (OPENBB_API_AUTH in credentials.env) is
 * OFF, which is the one state in which this door must not open (lock first, then door).
 * openbq-docker serves no /ai, so there is no Rita leg. When the wire is
 * configured, rss-ticker must answer both of the shapes the /news family relays: one page of
 * history for an APPROVED feed, and a socket handshake. The handshake is a handshake only --
 * no subscription frame is ever sent, so no feed is polled and no article body is fetched.
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
    console.log("PASS: openbq-api authenticates the stack pair and is locked; the wire's history/socket answer if configured. No quote or feed subscription requested.");
  } catch (error) { console.error(`STOP: ${error.message}; no public route should be opened.`); process.exitCode = 1; }
}
