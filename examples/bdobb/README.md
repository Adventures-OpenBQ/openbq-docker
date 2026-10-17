<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# BDOBB example dashboards

`apps.json` holds the BDOBB example dashboards this backend serves on `/apps.json`, next to the
provider apps: one combined file with every BDOBB example from v3 through this release (BDOBB vN
pairs with openbq-docker vN). It is generated from BDOBB's `docs/examples` by BDOBB's
`scripts/apps-sync.mjs` and committed here; until then it is the empty list `[]`. The image copies it
to `/workspace/bdobb_apps.json`, and `lanes/openbq_lanes.py` appends it to the built catalog
(`OPENBQ_EXTRA_APPS`), because openbb-api's own `/apps.json` drops apps whose cards are not backend
widgets.

The catalog is checked once, when it is first built: any app (example or provider) with a card that is
neither in `/widgets.json` nor a BDOBB built-in (note, markdown, website, clock, rss, news, date_probe,
param_echo, period_echo, local_table, linked_table, linked_chart) is dropped from `/apps.json`, and the
API log names the app and the missing widget ids. A provider missing from the image therefore removes
its examples instead of shipping blank cards.

## Logo

The examples' `img` is `/openbq/bdobb-logo.svg`, which the lanes hook serves as `image/svg+xml`
without Basic auth (Workspace fetches app images without credentials); every other path keeps the
API's auth. The file is `examples/episode3/assets/bdobb-logo.svg`, copied into the image as
`/workspace/bdobb-logo.svg` (`OPENBQ_BDOBB_LOGO`). It is the SVG BDOBB's `scripts/apps-sync.mjs`
embeds in `img_dark`/`img_light` (it reads this very file), and is byte-identical to BDOBB
`src/assets/branding/bdobb-app-square.svg` at 93bf2633 (2026-10-06; sha256
`3588fcde88197d2761bf489208a385d234440da9f59174a113bdae96070d3878`), Copyright 2026
SecretoftheUniverse.com LLC, Apache-2.0. BDOBB later renamed its title from BDOBB2 to BDOBB (b6c0ce7d);
the paths are unchanged.
