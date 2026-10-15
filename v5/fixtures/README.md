<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Fixture widgets (v5)

BDOBB's *V5 Statement Example* (`docs/examples/v5-financial-demo/apps.json`) has one card,
**`synthetic_cash_flow`**, which BDOBB's own example served from a local `python3 -m http.server`. This
backend serves it instead, with the same widget id and the same rows:

- `widgets.json` lists the widget; the lanes hook (`lanes/openbq_lanes.py`) adds it to `/widgets.json`.
  Its fields are BDOBB's (`name`, `description`, `type: table`, no params), in openbb-api's widget
  shape (`widgetId`, `category`, `gridData`, `source`); the endpoint is this backend's
  `/api/v1/openbq/fixtures/synthetic_cash_flow`.
- `synthetic_cash_flow.json` is the data, served as is (a JSON list of two rows: FY2026 Q3 operating
  cash flow 12 and capital expenditure -5; TTM 33 and -18). Fictional, not investment data.

The image copies this directory to `/workspace/openbq-fixtures` (`OPENBQ_FIXTURES`). The data route
follows the API's Basic auth, like any data route, and sits under `/api/v1/` so that the v8 Funnel
door's route rule (funnel-gateway/policy.mjs) admits it like any widget call.

Provenance: `synthetic_cash_flow.json` is byte-identical to BDOBB
`docs/examples/v5-financial-demo/cash-flow.json` (blob `a2d6e419`, added in 9e007077, 2026-10-07,
unchanged through release/v10), and the widget's name, description and type come from the
`widgets.json` beside it (blob `c82aaea0`). Copyright 2026 SecretoftheUniverse.com LLC, Apache-2.0.
