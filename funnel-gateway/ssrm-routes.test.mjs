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

const originalRoutes = [
  [
    "bls_jolts_revisions_bls_obb",
    "/api/v1/bls/jolts/revisions"
  ],
  [
    "eia_petroleum_imports_exports_and_movements_movements_of_crude_oil_and_selected_products_by_rail_eia_obb",
    "/api/v1/eia/petroleum/imports_exports_and_movements/movements_of_crude_oil_and_selected_products_by_rail"
  ],
  [
    "tmx_fixedincome_prices_tmx_obb",
    "/api/v1/tmx/fixedincome/prices"
  ],
  [
    "eia_petroleum_refining_and_processing_refinery_net_input_eia_obb",
    "/api/v1/eia/petroleum/refining_and_processing/refinery_net_input"
  ],
  [
    "eia_natural_gas_consumption_end_use_natural_gas_consumption_by_end_use_eia_obb",
    "/api/v1/eia/natural_gas/consumption_end_use/natural_gas_consumption_by_end_use"
  ],
  [
    "eia_coal_by_mine_by_plant_eia_obb",
    "/api/v1/eia/coal/by_mine_by_plant"
  ],
  [
    "ecb_eligible_assets_ecb_obb",
    "/api/v1/ecb/eligible_assets"
  ],
  [
    "eia_petroleum_refining_and_processing_refinery_blender_net_input_eia_obb",
    "/api/v1/eia/petroleum/refining_and_processing/refinery_blender_net_input"
  ],
  [
    "eia_petroleum_refining_and_processing_refinery_net_production_eia_obb",
    "/api/v1/eia/petroleum/refining_and_processing/refinery_net_production"
  ],
  [
    "eia_petroleum_refining_and_processing_natural_gas_plant_field_production_eia_obb",
    "/api/v1/eia/petroleum/refining_and_processing/natural_gas_plant_field_production"
  ],
  [
    "imf_chokepoint_volume_imf_obb",
    "/api/v1/imf/chokepoint_volume"
  ],
  [
    "eia_petroleum_imports_exports_and_movements_movements_by_tanker_and_barge_between_pad_districts_eia_obb",
    "/api/v1/eia/petroleum/imports_exports_and_movements/movements_by_tanker_and_barge_between_pad_districts"
  ],
  [
    "eia_natural_gas_prices_natural_gas_prices_eia_obb",
    "/api/v1/eia/natural_gas/prices/natural_gas_prices"
  ],
  [
    "eia_petroleum_prices_weekly_retail_gasoline_and_diesel_prices_eia_obb",
    "/api/v1/eia/petroleum/prices/weekly_retail_gasoline_and_diesel_prices"
  ],
  [
    "eia_petroleum_status_report_eia_obb",
    "/api/v1/eia/petroleum_status_report"
  ],
  [
    "cftc_fx_forward_trades_cftc_obb",
    "/api/v1/cftc/fx_forward_trades"
  ],
  [
    "eia_natural_gas_summary_natural_gas_summary_eia_obb",
    "/api/v1/eia/natural_gas/summary/natural_gas_summary"
  ],
  [
    "cftc_swap_trades_cftc_obb",
    "/api/v1/cftc/swap_trades"
  ],
  [
    "ny_market_expectations_federal_reserve_obb",
    "/api/v1/federal_reserve/ny/market_expectations"
  ],
  [
    "ffiec_institutions_federal_reserve_obb",
    "/api/v1/federal_reserve/ffiec/institutions"
  ],
  [
    "finra_fixedincome_bonds_finra_obb",
    "/api/v1/finra/fixedincome/bonds"
  ],
  [
    "finra_fixedincome_bond_prices_finra_obb",
    "/api/v1/finra/fixedincome/bond_prices"
  ],
  [
    "ffiec_institution_structure_federal_reserve_obb",
    "/api/v1/federal_reserve/ffiec/institution_structure"
  ]
];

test("the committed list preserves 23 routes and adds 18 distinct EIA paging routes", () => {
  for (const [id, route] of originalRoutes) assert.ok(widgets.some(w => w.id === id && w.route === route));
  const additions = widgets.filter(w => !originalRoutes.some(([id]) => w.id === id));
  assert.equal(additions.length, 18);
  for (const widget of additions) assert.match(widget.route, /\/eia\//);
  assert.equal(widgets.length, 41);
  assert.equal(new Set(widgets.map(w => w.id)).size, 41);
  assert.equal(new Set(doorPaths).size, 41);
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

test("a settings file without ssrmRoutes admits all 41 routes; an explicit list still wins", () => {
  const settings = { origin: `https://openbq.${["example-tailnet", "ts", "net"].join(".")}:10000` };
  const secrets = { token: "t".repeat(32), apiUsername: "u", apiPassword: "p" };
  assert.deepEqual(validateConfig(settings, secrets).ssrmRoutes, doorPaths);
  assert.deepEqual(validateConfig({ ...settings, ssrmRoutes: [] }, secrets).ssrmRoutes, []);
});
