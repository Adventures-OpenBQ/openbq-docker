<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# funnel-gateway (openbq-docker v8.0.0, `web` profile)

The door the sidecar publishes on Funnel port 10000 for BDOBB's browser (web) preview. Port 443
stays `openbq-api` for your tailnet and is never funneled; 8443 belongs to the episode 3 reference
backend (tailnet-only), so both run on one node. Ported from bdobb-dev/openbb-docker
**v8.0.3** (`775354f`, `funnel-gateway/`, Apache-2.0) with the `/ai` (Rita) family and its SOCKS5
dialer removed; the route contract is otherwise unchanged, so BDOBB's vendored `web/policy.mjs`
and this `policy.mjs` agree byte for byte on what is admitted.

## Isolation and lock-first

`funnel-gateway` and `rss-ticker` are compose services under `profiles: [web]`:
`docker compose -f docker-compose.yml -f docker-compose.v3.yml up -d` never starts them;
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
| `/api/widgets.json`, `/api/apps.json` | GET | openbq-api's root documents with the Basic pair injected; no query; bodies up to 16 MiB (every other route: 2 MiB) |
| `/ref/widgets.json`, `/ref/apps.json` | GET | the reference backend's root documents, keyless (no credential is injected); no query; bodies up to 16 MiB |
| `/ref/agents.json`, `/ref/bundle.apps.json`, `/ref/market-examples.apps.json`, `/ref/assets/bdobb-logo.svg` | GET | the four other exact documents the reference serves with a dot in the path; no query; nothing else dotted passes |
| `GET /ref/<path>` | GET | the reference's other routes, keyless, under the same structural bounds as `/api/api/v1` (lowercase segments, no dot, no `%`, bounded query, re-serialised); any `omni*` segment at any depth is refused |
| `/api/api/v1/**` | GET | under the shape bounds (lowercase route ≤ 200 chars, ≤ 40 query pairs, name grammar, ≤ 1024-char values, no control characters, ≤ 4096 chars leaving), query re-serialised |
| `/api/api/v1/calendar/trading` | GET | only `exchange=<MIC>&year=1990..2040` |
| `/news/api/news?feed_id=<id>&limit=<1-50>` | GET | rss-ticker's history page for **one approved feed id**; no credential |
| `/news/ws/news` | GET + Upgrade | the wire's socket (below); `503` until `feeds` names a feed |
| `/state/<digits>` | GET | the user's saved files `{files: {name: text}}` |
| `/state/<digits>/<file>` | PUT, DELETE | one of the app's JSON stores (`policy.mjs` `stateFile`); 256 KiB a file, 2 MiB and 200 files a user; `application/json` only |
| `/ai/**` | — | not served by openbq-docker: 404 (POST 405) |
| `/ref/live_grid_ws` | WebSocket | the reference's live grid, keyless: the token plus `Origin` = `origin`, or a single-use 30 s ticket (5 s of signer clock skew tolerated) plus `Origin` = `previewOrigin` (tickets off while unset); no query, no subprotocol; every frame must be `{"params":{"symbol":"A,B"}}` (rebuilt before it is forwarded) or the socket closes; `maxSockets`, no lifetime (a 30 s ping; a missed pong closes it), 10 s to the first frame |
| any other WebSocket upgrade | — | 401 without the token, else 403 (foreign Origin) or 404 |
| everything else | — | 404 |

Caps (settings): `maxConcurrent` (8, ≤ 32) and `maxSockets` (4, ≤ 32, shared by `/news/ws/news`
and `/ref/live_grid_ws`). There is no daily vendor cap and no per-minute request budget (removed
2026-10-17; `quoteDailyLimit` and `requestsPerMinute` are refused at startup by name, so delete them
from an older settings file). Counters are in memory and reset on restart; keep one instance.

Managed table cancellation and cleanup reserve **two concurrent requests** outside
`maxConcurrent`. Only exact, query-free `POST /table/sessions/:id/cancel`,
`DELETE /table/sessions/:id` and `DELETE /table/exports/:id` qualify, after route
validation and bearer authentication. A full control lane returns 429, with no borrowing
from the ordinary lane.
Body limits, identity assertions, deadlines and disconnect cleanup still apply.
Source deletion, derive/commands/export creation and standard LIVE requests use
the ordinary concurrency limit. See [managed tables](../table-service/README.md).

## The wire (`/news`)

`feeds` in `settings.json` maps each **approved** feed URL to its rss-ticker id. It is the whole
access control: rss-ticker has no authentication, and the door takes no feed URL from any caller.
`/news/api/news` names a feed only by an approved id; the socket's single subscription frame
`{"subscribe":[{"url":…}]}` (1–50 unique urls, no other key) is rebuilt from the approved urls
alone, unapproved ones dropped, and closed if none is left. A second frame, a binary or oversized
frame closes it. Going back, the door forwards the `{"feeds":…}` reply and articles whose
`feed_id` is an approved id, drops any other frame, and closes on one that is not JSON. The upstream opens only after a valid frame; a socket has no lifetime (a 30 s ping closes one
whose client stops answering) and must send its frame within 10 s; frames are capped at 64 KiB.

```json
{
  "rssOrigin": "https://openbq.YOUR-TAILNET.ts.net:8088",
  "rssAddress": "<the tailnet IPv4 rssOrigin resolves to>",
  "feeds": { "https://feeds.example.com/news.xml": 7 }
}
```

The gateway dials rss-ticker by its **tailnet HTTPS name** (`rssOrigin`, port 8088 as
`ts-config/serve-funnel.json` publishes it, or portless) at the **pinned tailnet IPv4**
`rssAddress`, never `http://rss-ticker:8088`: the pool may move to another node without the
contract changing. A bridge container reaches the tailnet CGNAT range only if the host routes it; check
before configuring the three keys (200 or 401 = routable):

```sh
docker run --rm --network openbq-stack_openbq-internal curlimages/curl \
  -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
  --resolve "openbq.<tailnet>.ts.net:8088:<rssAddress>" \
  "https://openbq.<tailnet>.ts.net:8088/api/news?feed_id=<an approved id>&limit=1"
```

If it is not routable, leave the three keys unset: the door serves `/api` and `/state`, and the
two `/news` routes answer 404/503.

## Socket tickets

A browser cannot carry the machine token on a WebSocket, so BDOBB's web layer (which checked the
GitHub session) signs a ticket and the browser opens
`wss://<origin>/news/ws/news?ticket=<expiry>.<nonce>.<sig>` directly:

- `expiry`: 13-digit epoch ms, at most 30 s ahead; `nonce`: 16 random bytes, base64url (22);
  `sig`: base64url (43) of `HMAC-SHA256(K, "<expiry>.<nonce>.<target>")` with
  `K = HMAC-SHA256(GATEWAY_TOKEN, "bdobb socket ticket v1")`; `target` is the canonical path and
  query `socketTarget()` returns (only `/news/ws/news`).
- The ticket is the last parameter, spelled literally, once; the request carries no
  `Authorization` and `Origin: <previewOrigin>`. Each nonce is admitted once. Tickets are off
  until `previewOrigin` is set.

## Configuration

- `gateway.env` (from `gateway.env.example`, `chmod 600`): `GATEWAY_TOKEN` (32–256 base64url;
  the web preview's `BACKEND_GATEWAY_TOKEN`), and `OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD`,
  the same pair as in `credentials.env` (repeated so the gateway never loads provider keys).
- `gateway-config/settings.json` (from `funnel-gateway/settings.example.json`, read-only bind):
  `origin` (`https://openbq.<tailnet>.ts.net:10000`), `previewOrigin` (the web preview's portless HTTPS origin, to turn socket tickets on; unset leaves them off), `stateDir`
  (`/var/lib/bdobb/state` to turn `/state` on), the caps, `rssOrigin`/`rssAddress`/`feeds`
  (both-or-neither; feeds need them) and the table keys (`tableService`, `tableDesktopPrincipal`,
  `ssrmRoutes`, `tableTimeoutMs`, `ssrmTimeoutMs`; see [managed tables](../table-service/README.md)). An unknown key,
  including Rita's `ritaOrigin`, `ritaAddress` and `socksProxy` and v10's `liveGrid`, is refused at startup.
- `rss-ticker-config/config.yaml` (from `config.yaml.example`).

## Ports and serve files

One Tailscale sidecar applies exactly one serve file: `ts-config/serve.json` normally, and
`ts-config/serve-v3.json` when the v3 overlay (`docker-compose.v3.yml`) is in use. Each has a Funnel
variant that adds only the door. Swap it in on the deployment host with `cp … .new && jq empty … && mv`;
the sidecar live-applies the file, and a malformed one would kill it.

| Serve file | Applied by | 443 | 8443 | 8088 | 10000 |
|---|---|---|---|---|---|
| `serve.json` | default compose | ODP (tailnet) | — | rss-ticker (tailnet) | — |
| `serve-funnel.json` | copied over `serve.json` | ODP (tailnet) | — | rss-ticker (tailnet) | **gateway (Funnel)** |
| `serve-v3.json` | the v3 overlay | ODP (tailnet) | reference (tailnet) | rss-ticker (tailnet) | — |
| `serve-v3-funnel.json` | copied over `serve-v3.json` | ODP (tailnet) | reference (tailnet) | rss-ticker (tailnet) | **gateway (Funnel)** |

Funnel offers only 443, 8443 and 10000; 10000 is the only port any file funnels
(`tests/test_web_profile.py` checks every file). 8088 answers 502 until the `web` profile runs.

## Verification

```sh
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web up -d
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node check-upstreams.mjs  # API pair works, API locked, wire answers
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node verify.mjs           # the door's own lock, on the bridge
cp ts-config/serve-v3-funnel.json ts-config/serve-v3.json.new && jq empty ts-config/serve-v3.json.new && mv ts-config/serve-v3.json.new ts-config/serve-v3.json   # the door opens; the sidecar live-applies it, and a malformed file would kill it
# a base stack without the v3 overlay swaps its own file instead:
# cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec -e GATEWAY_URL=https://openbq.<tailnet>.ts.net:10000 funnel-gateway node verify.mjs
```

`git checkout ts-config/serve.json` and a sidecar restart close the door again. Then test from a
device off the tailnet. Neither preflight queries a quote, subscribes to a feed or prints a credential. Tests: `cd
funnel-gateway && npm ci --ignore-scripts && npm test`. In Docker, mount the repo root (`-v "$PWD:/r" -w /r/funnel-gateway`), because the version test reads `../docker-compose.yml`.
