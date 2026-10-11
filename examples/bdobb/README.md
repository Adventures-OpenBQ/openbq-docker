<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# BDOBB example dashboards

`apps.json` holds the BDOBB example dashboards this backend serves on `/apps.json`, next to the
provider apps. It is generated from BDOBB's `docs/examples` (`EPISODE=7 pnpm apps:sync`), keeping only
the examples whose cards are BDOBB built-ins or widgets this backend serves. The image copies it to
`/workspace/bdobb_apps.json`, and `lanes/openbq_lanes.py` appends it to the built catalog
(`OPENBQ_EXTRA_APPS`), because openbb-api's own `/apps.json` drops apps whose cards are not backend widgets.
