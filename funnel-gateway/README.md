<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# funnel-gateway (openbq-docker v4.0.0, `web` profile)

The door the sidecar publishes on Funnel port 10000 for BDOBB's browser (web) preview. Port 443
stays `openbq-api` for your tailnet and is never funneled; 8443 belongs to the episode 3 reference
backend (tailnet-only), so both run on one node. Brought down from openbq-docker **v8.0.0**
(itself ported from bdobb-dev/openbb-docker v8.0.3, `775354f`, Apache-2.0, without the `/ai`
family) without the `/news` wire, which arrives at v8, and with the managed-table routes of
openbq-docker PR #10. BDOBB v4's vendored `web/policy.mjs` and this `policy.mjs` agree byte for
byte on what is admitted. What was left at v8 and v10 is listed in
[docs/v4/gateway-down.md](../docs/v4/gateway-down.md).

## Isolation and lock-first

`funnel-gateway` is a compose service under `profiles: [web]`:
`docker compose -f docker-compose.yml -f docker-compose.v3.yml up -d` never starts it;
`docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web up -d` does. The gateway joins the
`openbq-internal` bridge (and, for the managed tables, the internal `table-private` bridge), listens on `0.0.0.0:8091` with no host port, and is reached only through
Tailscale Serve. It runs `read_only`, as uid 1000, `cap_drop: [ALL]`, 512 MB, 64 pids; its only
writable mount is the `gateway-state` volume behind `/state`.

Nothing is public until two separate steps both happen: the profile is started, **and** the
sidecar's Serve config is swapped to its Funnel variant (a deliberate copy, never automatic; see
the table below). Before the swap, run both preflights below. The API's
own lock must be on first: `OPENBB_API_AUTH=true` with a Basic pair in `credentials.env`;
`check-upstreams.mjs` refuses to pass an open API.

## Routes

Every request, including health, needs exactly one `Authorization: Bearer <GATEWAY_TOKEN>`
(timing-safe). `Host` must be the configured `origin`; an `Origin`, if present, must equal it or be
one of the packaged desktop app's two webview origins, `tauri://localhost` and `http://tauri.localhost`
(V10-P1; the Bearer token is still required, and the dev server's `http://localhost:1420` is refused).
Caller headers, cookies and credentials are never relayed.

| Route | Method | What happens |
|---|---|---|
| `/_gateway/health` | GET | `200 {"ok":true}` behind the lock |
| `/api/widgets.json`, `/api/apps.json` | GET | openbq-api's root documents with the Basic pair injected; no query; not metered daily; bodies up to 16 MiB (every other route: 2 MiB) |
| `/ref/widgets.json`, `/ref/apps.json` | GET | the reference backend's root documents, keyless (no credential is injected); no query; bodies up to 16 MiB |
| `/ref/agents.json`, `/ref/bundle.apps.json`, `/ref/market-examples.apps.json`, `/ref/assets/bdobb-logo.svg` | GET | the four other exact documents the reference serves with a dot in the path; no query; nothing else dotted passes |
| `GET /ref/<path>` | GET | the reference's other routes, keyless, under the same structural bounds as `/api/api/v1` (lowercase segments, no dot, no `%`, bounded query, re-serialised); any `omni*` segment at any depth is refused |
| `/api/api/v1/**` | GET | under the shape bounds (lowercase route ≤ 200 chars, ≤ 40 query pairs, name grammar, ≤ 1024-char values, no control characters, ≤ 4096 chars leaving), query re-serialised |
| `/api/api/v1/calendar/trading` | GET | only `exchange=<MIC>&year=1990..2040` |
| `/table/**`, `ssrmRoutes` POSTs | see below | the managed table service and registered OpenBB SSRM endpoints |
| `/state/<digits>` | GET | the user's saved files `{files: {name: text}}` |
| `/state/<digits>/<file>` | PUT, DELETE | one of the app's JSON stores (`policy.mjs` `stateFile`); 256 KiB a file, 2 MiB and 200 files a user; `application/json` only |
| `/ai/**` | — | not served by openbq-docker: 404 (POST 405) |
| `/news/**` | — | the wire arrives at v8: 404 |
| `/ref/live_grid_ws` | WebSocket | the reference's live grid, keyless: the token plus `Origin` = `origin`, or a single-use 30 s ticket (5 s of signer clock skew tolerated) plus `Origin` = `previewOrigin` (tickets off while unset); no query, no subprotocol; every frame must be `{"params":{"symbol":"A,B"}}` (rebuilt before it is forwarded) or the socket closes; `maxSockets`, no lifetime (a 30 s ping; a missed pong closes it), 10 s to the first frame |
| any other WebSocket upgrade | — | 401 without the token, else 403 (foreign Origin) or 404 |
| everything else | — | 404 |

Caps (settings): `maxConcurrent` (8, ≤ 32) and `maxSockets` (4, ≤ 32). There is no daily vendor
cap and no per-minute request budget (removed 2026-10-17; `quoteDailyLimit` and `requestsPerMinute`
are refused at startup by name, so delete them from an older settings file). Counters are in
memory and reset on restart; keep one instance.

Managed table cancellation and cleanup reserve **two concurrent requests** outside
`maxConcurrent`. Only exact, query-free `POST /table/sessions/:id/cancel`,
`DELETE /table/sessions/:id` and `DELETE /table/exports/:id` qualify, after route
validation and bearer authentication. A full control lane returns 429, with no borrowing
from the ordinary lane.
Body limits, identity assertions, deadlines and disconnect cleanup still apply.
Source deletion, derive/commands/export creation and standard LIVE requests use
the ordinary concurrency limit. See [managed tables](../table-service/README.md).

## Configuration

- `gateway.env` (from `gateway.env.example`, `chmod 600`): `GATEWAY_TOKEN` (32–256 base64url;
  the web preview's `BACKEND_GATEWAY_TOKEN`), and `OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD`,
  the same pair as in `credentials.env` (repeated so the gateway never loads provider keys).
- `gateway-config/settings.json` (from `funnel-gateway/settings.example.json`, read-only bind):
  `origin` (`https://openbq.<tailnet>.ts.net:10000`), `stateDir` (`/var/lib/bdobb/state` to turn
  `/state` on), `previewOrigin` (the web preview's portless HTTPS origin, to turn socket tickets on; the example leaves it unset, so tickets stay off until a Vercel origin exists), the caps, and the table keys (`tableService`, `tableDesktopPrincipal`,
  `ssrmRoutes`, `tableTimeoutMs`, `ssrmTimeoutMs`; see [managed tables](../table-service/README.md)). An unknown
  key is refused at startup, including Rita's `ritaOrigin`, `ritaAddress` and `socksProxy` and
  the keys of later lines (`rssOrigin`, `rssAddress` and `feeds` at v8; `liveGrid` at v10).

## Ports and serve files

One Tailscale sidecar applies exactly one serve file: `ts-config/serve.json` normally, and
`ts-config/serve-v3.json` when the v3 overlay (`docker-compose.v3.yml`) is in use. Each has a Funnel
variant that adds only the door. Swap it in on the deployment host with `cp … .new && jq empty … && mv`;
the sidecar live-applies the file, and a malformed one would kill it.

| Serve file | Applied by | 443 | 8443 | 10000 |
|---|---|---|---|---|
| `serve.json` | default compose | ODP (tailnet) | — | — |
| `serve-funnel.json` | copied over `serve.json` | ODP (tailnet) | — | **gateway (Funnel)** |
| `serve-v3.json` | the v3 overlay | ODP (tailnet) | reference (tailnet) | — |
| `serve-v3-funnel.json` | copied over `serve-v3.json` | ODP (tailnet) | reference (tailnet) | **gateway (Funnel)** |

Funnel offers only 443, 8443 and 10000; 10000 is the only port any file funnels
(`tests/test_web_profile.py` checks every file).

## Verification

```sh
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web up -d
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node check-upstreams.mjs  # API pair works, API locked
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node verify.mjs           # the door's own lock, on the bridge
cp ts-config/serve-v3-funnel.json ts-config/serve-v3.json.new && jq empty ts-config/serve-v3.json.new && mv ts-config/serve-v3.json.new ts-config/serve-v3.json   # the door opens; the sidecar live-applies it, and a malformed file would kill it
# a base stack without the v3 overlay swaps its own file instead:
# cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec -e GATEWAY_URL=https://openbq.<tailnet>.ts.net:10000 funnel-gateway node verify.mjs
```

`git checkout ts-config/serve.json` and a sidecar restart close the door again. Then test from a
device off the tailnet. Neither preflight queries a quote or prints a credential. Tests: `cd
funnel-gateway && npm ci --ignore-scripts && npm test`. In Docker, mount the repo root (`-v "$PWD:/r" -w /r/funnel-gateway`), because the version test reads `../docker-compose.yml`.
