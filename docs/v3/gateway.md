<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# The gateway at v3

The funnel-gateway moves down to v3 so BDOBB's browser preview can reach the episode 3 reference
backend, including its live grid socket, through the one Funnel door. This file lists what came
down and what stayed up.

## Came down

- `funnel-gateway/` as brought down for the walk's v4 (itself from openbq-docker v8.0.0), minus
  PR #10's managed-table routes, the table service and `control-admission.test.mjs` (no tables
  at v3), plus v8's socket door: ticketed browser upgrades, `previewOrigin`, `maxSockets`, the
  `ws` dependency. A socket has no lifetime: a 30 s ping closes one whose client stops answering.
- The compose `funnel-gateway` service (`web` profile, `openbq-funnel-gateway:3.0.0`), the
  `gateway-state` volume, `gateway.env.example`, `ts-config/serve-funnel.json` and
  `serve-v3-funnel.json` (the :10000 door), `tests/test_web_profile.py` and the CI steps.

## New at v3: `/ref`

- `/ref/widgets.json` and `/ref/apps.json` (exact, no query) forward to the reference backend
  (`openbq-reference:17783`, the v3 overlay's service) with no credential: the reference is a
  keyless local fixture.
- Every other GET under `/ref/` obeys the same structural rule as `/api/api/v1` (lowercase
  segments, no dot, no `%`, bounded and re-serialised query), and any `omni*` segment at any
  depth is refused, so no code-executing Omni route is forwarded.
- Consequence: a path with a dot is refused unless it is one of the exact documents
  `agents.json`, `bundle.apps.json`, `market-examples.apps.json` or `assets/bdobb-logo.svg`.
- `/ref/live_grid_ws` is the one socket. Its frames are rebuilt by `refSubscription` from the
  single value that passed the symbol grammar, the upstream is dialled keyless (`connectRef`),
  and no vendor quota is metered (the reference holds no vendor key).

The `/ref` upstream needs the v3 overlay (`docker-compose.v3.yml`), whose reference service
carries the `openbq-reference` alias on `openbq-internal`; the gateway sits on the same network.

## Routes served

`/_gateway/health`, `/api/**`, `/state/**`, `/ref/**` and the `/ref/live_grid_ws` socket. Anything
else is 404; any other upgrade is refused.

## Stayed up

| Left out | Stays at | Why |
|---|---|---|
| `/news/api/news`, the `/news/ws/news` socket, `rss-ticker`, settings `rssOrigin`, `rssAddress`, `feeds` | v8 | The RSS wire is a v8 feature. |
| `/grid/**` sockets, `liveGrid`, `/grid/ws_ticket` | v10 | Live grid is a v10 feature. |
| `/table/**`, the table service and its settings | later | Managed tables are not at v3. |
