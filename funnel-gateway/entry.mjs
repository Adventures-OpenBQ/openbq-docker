// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import { readConfig } from "./config.mjs";
import { createGateway } from "./server.mjs";

try {
  const gateway = createGateway(readConfig());
  // 0.0.0.0 inside this container's own namespace: the only way in is the openbq-internal
  // bridge (no host port is published), and Serve proxies to funnel-gateway:8091 by name.
  // listen() reports failure (port taken, address unavailable) asynchronously, so the
  // try below never sees it; without this the process would idle, healthy-looking, deaf.
  gateway.on("error", () => { console.error("Gateway could not listen; refusing to serve."); process.exit(1); });
  gateway.listen(8091, "0.0.0.0", () => console.log("Gateway listening on the bridge; published only through Serve."));
  for (const signal of ["SIGTERM", "SIGINT"]) process.once(signal, async () => {
    await gateway.closeGateway(); process.exit(0);
  });
} catch {
  console.error("Gateway configuration invalid or inaccessible; refusing to listen.");
  process.exitCode = 1;
}
