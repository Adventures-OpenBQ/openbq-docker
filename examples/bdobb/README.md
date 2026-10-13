<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# BDOBB example dashboards

`apps.json` holds the BDOBB example dashboards this backend serves on `/apps.json`, next to the
provider apps. It is generated from BDOBB's `docs/examples` (`EPISODE=3 pnpm apps:sync`), keeping only
the examples whose cards are BDOBB built-ins or widgets this backend serves. The image copies it to
`/workspace/bdobb_apps.json`, and `lanes/openbq_lanes.py` appends it to the built catalog
(`OPENBQ_EXTRA_APPS`), because openbb-api's own `/apps.json` drops apps whose cards are not backend widgets.

Each example card carries the BDOBB logo (`examples/episode3/assets/bdobb-logo.svg`). `img` is
`/openbq/bdobb-logo.svg`, which the lanes hook serves without Basic auth: BDOBB shows only http(s) card
images, resolved against the backend URL, and an `<img>` sends no auth header. `img_dark` and `img_light`
embed the same SVG as a data URI, as the Episode 3 apps do, for clients that take one. BDOBB skips the
data URI and falls back to `img`.

Examples are left out when a card is neither a BDOBB built-in nor a widget in this backend's
`/widgets.json`: Demo providers (EIA, EconDB, BLS, Alpha Vantage and Videos cards) and Video Library
(Videos card).
