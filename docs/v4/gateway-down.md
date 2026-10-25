<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# The gateway at v4

User ruling, 2026-10-15: the funnel-gateway moves down from v8 to v4, so the managed
server-side tables (openbq-docker PR #10) can sit behind it from v4. This file lists what
came down from openbq-docker v8.0.0 (`origin/release/v8`, introduced in 175461d, then
d1a7ff9 and 2a4d087) and what stayed up.

## Came down

- `funnel-gateway/`: `server.mjs`, `policy.mjs`, `config.mjs`, `entry.mjs`,
  `healthcheck.mjs`, `verify.mjs`, `check-upstreams.mjs`, `Dockerfile`, `README.md`,
  `settings.example.json`, `package.json`, `package-lock.json`.
- Routes: `/_gateway/health`, `/api/widgets.json`, `/api/apps.json`, `/api/api/v1/**`
  (including `calendar/trading`, which v4 already serves and the v4 client calls), and
  `/state/**`.
- The socket-ticket signer and verifier in `policy.mjs`, with a `socketTarget` that admits
  nothing at this tag. BDOBB v4's web relay vendors and calls them.
- The compose `funnel-gateway` service (`web` profile, `openbq-funnel-gateway:4.0.0`), the
  `gateway-state` volume, `gateway.env.example`, `ts-config/serve-funnel.json` and
  `serve-v3-funnel.json` (the :10000 door), the ignores, `tests/test_web_profile.py` and the
  CI steps.
- Tests: `gateway.test.mjs` and `policy.test.mjs` minus the wire's cases.
- From PR #10 (41641c6): `tableRoute`, `tableControlRoute`, `validSsrmRoutes` and the table
  constants in `policy.mjs`; the table relay, principal and control lane in `server.mjs`; the
  table settings and secrets in `config.mjs`; the table lines in `gateway.env.example`; its
  table tests and `control-admission.test.mjs`.

## The desktop Origin rule (V10-P1's HTTP half)

User ruling, 2026-10-15: the gateway accepts the packaged desktop app's webview origins,
`tauri://localhost` and `http://tauri.localhost`, alongside its own origin, on Bearer-authenticated
HTTP for every route, `/table` included. Tauri's http plugin stamps one of them on every request,
so without the rule the packaged desktop and the v7 iPad got 403 on `/table`. The same origins
without the Bearer token are still refused (401), and the dev server's `http://localhost:1420` never
passes (403). The rule is v10's (`DESKTOP_ORIGINS` and the Origin check from 76fd6a3); `policy.mjs`
does not change. The desktop socket ticket (`/grid/ws_ticket`) and desktop socket upgrades stay at
v10: at v4 an upgrade from a desktop origin is refused like any other.

## Stayed up

| Left out | Stays at | Why |
|---|---|---|
| `/news/api/news`, the `/news/ws/news` socket, `newsSubscription`, `connectNews`, the pinned tailnet TLS dial | v8 | The RSS wire is a v8 feature. |
| `rss-ticker` service, `rss-ticker-config/`, its volume, ignores and Serve port 8088 | v8 | Same. |
| `tls.test.mjs` and the wire's preflight and verifier probes | v8 | They test only the wire. |
| Settings `rssOrigin`, `rssAddress`, `feeds` | v8 | The wire's configuration; refused as unknown keys at v4. |
| The socket door in `server.mjs` (ticketed browser upgrades, socket budget, the dead-peer heartbeat), settings `previewOrigin` and `maxSockets`, the `ws` dependency | v8 | Its only route is the wire's socket. At v4 every upgrade is refused (401 without the token, else 404). |
| `/grid/**`, the `/grid` sockets and subscriptions, `liveGrid` | v10 | Live grid is a v10 feature. |
| `/grid/ws_ticket` and desktop-Origin socket upgrades (V10-P1's socket half) | v10 | They serve the `/grid` sockets only. |
| PR #10's `^` / `%5E` handling in `requestUrl` and `subscriptionRoute` | v10 | It serves `/grid` subscriptions. |
| PR #10's `.env.example` `TABLE_*` lines | v10 | Per the walk map. |
| PR #10's `node:26.10.0-alpine` base image | not taken | The gateway tests pass on Node 22 (v8's `node:22-alpine`), so v4 keeps it. |

The `docks` hidden dashboard paragraph in v8's README is a v8 feature and is not repeated here.

## The web preview at v4

User ruling, 2026-10-15: BDOBB's web preview is offered from v4, over HTTP. It needs nothing more
from v8. `/api`, `/state` and `/table` above are its whole surface. `previewOrigin` and the socket
door stay at v8, because they serve socket tickets only, and v4 has no socket route. A scratch run
put BDOBB v4's `web/server.mjs` in front of this gateway's `createGateway` at edf7447: catalogue,
data route and `/state` round trip passed, and `/api/docs` was refused. The policy did not change,
so the vendored policy bytes still held. (BDOBB's `openbqDocker` names the walk's latest paired
commit; see BDOBB's `docs/releases/v4-ssrm-walk.md`.)
