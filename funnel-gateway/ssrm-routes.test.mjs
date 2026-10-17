// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { tableRoute, validSsrmRoutes } from "./policy.mjs";
import { validateConfig } from "./config.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const widgets = JSON.parse(readFileSync(join(here, "..", "lanes", "ssrm_widgets.json"), "utf8"));
// The door prefixes the client route with /api and the handler suffixes /ssrm.
const doorPaths = widgets.map(w => `/api${w.route}/ssrm`);

test("the committed list is 23 unique routes the gateway's validator accepts", () => {
  assert.equal(widgets.length, 23);
  assert.equal(new Set(widgets.map(w => w.id)).size, 23);
  assert.equal(new Set(doorPaths).size, 23);
  assert.ok(validSsrmRoutes(doorPaths));
});

test("every committed SSRM route admits a POST and an unlisted sibling does not", () => {
  const config = { ssrmRoutes: doorPaths };
  for (const path of doorPaths) {
    const admitted = tableRoute(new URL(path, "https://example.com"), "POST", config);
    assert.ok(admitted && admitted.managed === false, path);
  }
  // A listed route carrying a widget param in the query string is still admitted.
  assert.ok(tableRoute(new URL(doorPaths[0] + "?start_date=2026-01-01", "https://example.com"), "POST", config));
  // An unlisted /ssrm POST and a GET on a listed route are both refused.
  assert.equal(tableRoute(new URL("/api/api/v1/not/listed/ssrm", "https://example.com"), "POST", config), null);
  assert.equal(tableRoute(new URL(doorPaths[0], "https://example.com"), "GET", config), null);
});

test("a settings file without ssrmRoutes admits the 23 routes; an explicit list still wins", () => {
  const settings = { origin: `https://openbq.${["example-tailnet", "ts", "net"].join(".")}:10000` };
  const secrets = { token: "t".repeat(32), apiUsername: "u", apiPassword: "p" };
  assert.deepEqual(validateConfig(settings, secrets).ssrmRoutes, doorPaths);
  assert.deepEqual(validateConfig({ ...settings, ssrmRoutes: [] }, secrets).ssrmRoutes, []);
});
