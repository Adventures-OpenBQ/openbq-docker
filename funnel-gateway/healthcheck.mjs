// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { request } from "node:http";
import { readConfig } from "./config.mjs";

// Exit 0 only when the gateway answers its own health route through the lock. Anything
// else -- bad config, no listener, a 401 -- is unhealthy. Prints nothing: no token, no origin.
try {
  const config = readConfig();
  const req = request({ host: "127.0.0.1", port: 8091, path: "/_gateway/health", timeout: 3000,
    headers: { Host: new URL(config.origin).host, Authorization: `Bearer ${config.token}` } }, res => {
    res.resume(); process.exit(res.statusCode === 200 ? 0 : 1);
  });
  req.on("timeout", () => { req.destroy(); process.exit(1); });
  req.on("error", () => process.exit(1));
  req.end();
} catch { process.exit(1); }
