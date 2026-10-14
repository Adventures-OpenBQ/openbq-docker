<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# BDOBB example dashboards

`apps.json` holds the BDOBB example dashboards this backend serves on `/apps.json`, next to the
provider apps: one combined file with every BDOBB example from v3 through this release (BDOBB vN
pairs with openbq-docker vN). It is generated from BDOBB's `docs/examples` by BDOBB's
`scripts/apps-sync.mjs` and committed here; until then it is the empty list `[]`. The image copies it
to `/workspace/bdobb_apps.json`, and `lanes/openbq_lanes.py` appends it to the built catalog
(`OPENBQ_EXTRA_APPS`), because openbb-api's own `/apps.json` drops apps whose cards are not backend
widgets.
