<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# funnel-gateway (openbq-docker v10.0.0, `web` profile)

The door the sidecar publishes on Funnel port 10000 for BDOBB's browser (web) preview. Port 443
stays `openbq-api` for your tailnet and is never funneled; 8443 belongs to the episode 3 reference
backend (tailnet-only), so both run on one node. Ported from bdobb-dev/openbb-docker
**v8.0.3** (`775354f`, `funnel-gateway/`, Apache-2.0) with the `/ai` (Rita) family and its SOCKS5
dialer removed; the route contract is otherwise unchanged, so BDOBB's vendored `web/policy.mjs`
and this `policy.mjs` agree byte for byte on what is admitted.

v10 adds the `/grid` family (live-grid, the opt-in `live` profile), ported from bdobb-dev/openbb-docker
**v10.1.7** (`d606169`): e8c1239 and 7212a1d (v10.0.3), b9545f5, d32966d, dc61be8, d7ec9d1 and
995e06a (v10.1.4). See [docs/v10/live-grid-kdb-port.md](../docs/v10/live-grid-kdb-port.md).

## Isolation and lock-first

`funnel-gateway` and `rss-ticker` are compose services under `profiles: [web]`: `docker compose
up -d` never starts them; `docker compose --profile web up -d` does. The gateway joins the
`openbq-internal` bridge, listens on `0.0.0.0:8091` with no host port, and is reached only through
Tailscale Serve. It runs `read_only`, as uid 1000, `cap_drop: [ALL]`, 256 MB, 64 pids; its only
writable mount is the `gateway-state` volume behind `/state`.

Nothing is public until two separate steps both happen: the profile is started, **and** the
sidecar's Serve config is swapped to its Funnel variant (a deliberate copy, never automatic; see
the table below). Before the swap, run both preflights below. The API's
own lock must be on first: `OPENBB_API_AUTH=true` with a Basic pair in `credentials.env`;
`check-upstreams.mjs` refuses to pass an open API.

## Routes

Every request, including health, needs exactly one `Authorization: Bearer <GATEWAY_TOKEN>`
(timing-safe). `Host` must be the configured `origin`; an `Origin`, if present, must equal it.
Caller headers, cookies and credentials are never relayed.

| Route | Method | What happens |
|---|---|---|
| `/_gateway/health` | GET | `200 {"ok":true}` behind the lock |
| `/api/widgets.json`, `/api/apps.json` | GET | openbq-api's root documents with the Basic pair injected; no query; not metered daily |
| `/api/api/v1/**` | GET | under the shape bounds (lowercase route ≤ 200 chars, ≤ 40 query pairs, name grammar, ≤ 1024-char values, no control characters, ≤ 4096 chars leaving), query re-serialised; one unit of `quoteDailyLimit` |
| `/api/api/v1/calendar/trading` | GET | only `exchange=<MIC>&year=1990..2040` |
| `/news/api/news?feed_id=<id>&limit=<1-50>` | GET | rss-ticker's history page for **one approved feed id**; no credential |
| `/news/ws/news` | GET + Upgrade | the wire's socket (below); `503` until `feeds` names a feed |
| `/state/<digits>` | GET | the user's saved files `{files: {name: text}}` |
| `/state/<digits>/<file>` | PUT, DELETE | one of the app's JSON stores (`policy.mjs` `stateFile`); 256 KiB a file, 2 MiB and 200 files a user; `application/json` only |
| `/grid/widgets.json`, `/grid/apps.json` | GET | live-grid's root documents with the Basic pair; no query; not metered. A `404` from an older live-grid is relayed as a bare `404` (optional documents) |
| `/grid/live_grid`, `/grid/symbol_meta` | GET | the quote grid's REST seed and its per-symbol metadata; `symbol` only, a comma list; **one unit of `quoteDailyLimit` each** |
| `/grid/series`, `/grid/chart` | GET | the bars, raw and as a figure; `symbol` (one), `interval`, `start`, `end`, `provider` (`kdb`/`eodhd`), plus `theme` (`light`/`dark`) on `chart` alone; one unit of `quoteDailyLimit` |
| `/grid/ticks` | GET | the kdb tick cache's newest ticks for one symbol; `symbol` (one), `limit` (1–1000); not metered (no vendor) |
| `/grid/ta_chart` | GET | the tick chart; `symbol` (one), `interval`, `source` (`local`/`eodhd`), `macro`, `indicators`, `anchor`, `start`, `end`, `theme`; `provider` is **not** mapped; one unit of `quoteDailyLimit` |
| `/grid/live_grid_ws` | GET + Upgrade | the quote grid's socket, no query; every params frame re-validated and metered per symbol (below) |
| `/grid/ta_chart_ws` | GET + Upgrade | the tick chart's push-only socket; its **query is its subscription** (the `/grid/ta_chart` grammar); every push metered, the first included |
| `/grid/subscriptions` | GET | live-grid's Subscriptions page, **the one route served without the token** (a frame cannot send one): exact path, no query, no body, this Host; HTML from memory after one fetch, with its own CSP. The page then asks BDOBB for the credential (`openbb-connect` → `openbb-auth`) |
| `/grid/api/subscriptions` | GET, POST | the watchlist behind the lock; POST takes `{"symbol": …}` (JSON, ≤ 1 KiB, one-symbol grammar), the body rebuilt from the validated symbol, **one unit of `quoteDailyLimit`** |
| `/grid/api/subscriptions/<symbol>` | DELETE | remove one symbol (one-symbol grammar, `^` literal) |
| `/grid/**` with `liveGrid` off | — | `503` (REST and sockets) after the route rules pass; an unmatched `/grid` path is still `404` |
| `/ai/**` | — | not served by openbq-docker: 404 (POST 405) |
| everything else | — | 404 |

Budgets (settings): `requestsPerMinute` (default 60, ≤ 600), `maxConcurrent` (8, ≤ 32),
`maxSockets` (4, ≤ 32), `quoteDailyLimit` (100, ≤ 10000, UTC day). A socket costs six units,
charged before the upgrade. Counters are in memory and reset on restart; keep one instance.

## The wire (`/news`)

`feeds` in `settings.json` maps each **approved** feed URL to its rss-ticker id. It is the whole
access control: rss-ticker has no authentication, and the door takes no feed URL from any caller.
`/news/api/news` names a feed only by an approved id; the socket's single subscription frame
`{"subscribe":[{"url":…}]}` (1–50 unique urls, no other key) is rebuilt from the approved urls
alone, unapproved ones dropped, and closed if none is left. A second frame, a binary or oversized
frame closes it. The upstream opens only after a valid frame; a socket lives at most 240 s and
must send its frame within 10 s; frames are capped at 64 KiB.

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
docker run --rm --network openbq-episode1_openbq-internal curlimages/curl \
  -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
  --resolve "openbq.<tailnet>.ts.net:8088:<rssAddress>" \
  "https://openbq.<tailnet>.ts.net:8088/api/news?feed_id=<an approved id>&limit=1"
```

If it is not routable, leave the three keys unset: the door serves `/api` and `/state`, and the
two `/news` routes answer 404/503.

## The grid (`/grid`, v10)

live-grid runs only under the opt-in `live` compose profile, so the door is told it runs:
`"liveGrid": true` in `settings.json`. Unset or `false`, every `/grid` route and socket answers
`503` once its route rules pass (the same state `/news` is in without the wire), and
`check-upstreams.mjs` does not dial live-grid. The origin is never a setting: it is
`http://live-grid:6903`, the compose service on `openbq-internal`, fixed in `config.mjs` like
`apiOrigin`; a `gridOrigin` key is refused.

**Credential.** Every grid request and both socket handshakes carry the stack's Basic pair (the
`OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD` in `gateway.env`). live-grid appends
`BasicAuthMiddleware` to its whole app, reading `OPENBB_API_AUTH` and the same pair from
`credentials.env`, so with the API's lock on it refuses everything else, its websocket handshake
included. Admission from the outside is unchanged: the Bearer machine token (or, for a browser
socket, a ticket) plus this route contract.

**Metering.** `/grid/live_grid`, `/grid/symbol_meta`, `/grid/series`, `/grid/chart` and
`/grid/ta_chart` reach a paid vendor (EODHD per symbol, or openbq-api's historical route), so each
spends one unit of the same `quoteDailyLimit` counter as `/api/api/v1/**`. The two manifests and
`/grid/ticks` are free. **Every** validated params frame on `/grid/live_grid_ws` charges one daily
unit **per symbol** in the rebuilt frame, the first frame included (the upgrade's six units buy
the slot and the per-minute budget for that first frame only; later frames cost one more
per-minute unit). **Every** upstream push on `/grid/ta_chart_ws` charges one daily unit, the first
included, and pushes after the first one per-minute unit. A charge that cannot be paid closes the
relay and hands the slot back.

**Frame cap.** `FRAME_CAP = 60` per socket lifetime (client frames on `live_grid_ws`, upstream
pushes on `ta_chart_ws`), hard-coded and checked before either budget. One tick-chart stream is
therefore at most 60 pushes (about 60 s at live-grid's default `TA_PUSH_INTERVAL_MS=1000`); a
larger `quoteDailyLimit` buys more streams, not longer ones. Both directions are bounded at
64 KiB a frame and 256 KiB of back-pressure; while live-grid's handshake is in flight only the
newest pending params frame is held.

**Frames.** `/grid/live_grid_ws` takes `{"params":{"symbol":"A,B"}}` on open and on every
parameter change; `liveGridSubscription` validates every frame and forwards one rebuilt from the
single value that passed. `/grid/ta_chart_ws` reads no frame at all: the door dials upstream at
upgrade with the query `socketTarget` re-serialised, and any client frame closes the relay.

**Not here.** `/grid/ta_registry`, `/grid/live_grid_studies` and the study sockets (later
lines), live-grid's `/demo`, `/health`, `/subscribe` and `/snapshot`, and the kdb+ tick cache
itself (q IPC executes arbitrary code with no auth).

**Subscriptions (V10-P5, 2026-10-13).** `/grid/widgets.json` rewrites the `subscriptions` iframe
widget's endpoint to `<origin>/grid/subscriptions`, so BDOBB frames this door's page, and
because the frame shares the backend's origin BDOBB hands it the Bearer header over the widget
postMessage protocol. live-grid refusals (404, 409, 422, 507) come back as the door's own short
messages. These routes are in `server.mjs`, not `policy.mjs` (vendored by BDOBB's web layer
under a hash test): the web preview's browser never holds this token, so the card works in the
desktop app, not the preview. `verify.mjs` does not probe the page to 200 (its first answer
fetches from live-grid); it proves the exception narrow instead.

## Socket tickets

A browser cannot carry the machine token on a WebSocket, so BDOBB's web layer (which checked the
GitHub session) signs a ticket and the browser opens
`wss://<origin>/news/ws/news?ticket=<expiry>.<nonce>.<sig>` directly (likewise
`/grid/live_grid_ws?ticket=…` and `/grid/ta_chart_ws?<validated query>&ticket=…`):

- `expiry`: 13-digit epoch ms, at most 30 s ahead; `nonce`: 16 random bytes, base64url (22);
  `sig`: base64url (43) of `HMAC-SHA256(K, "<expiry>.<nonce>.<target>")` with
  `K = HMAC-SHA256(GATEWAY_TOKEN, "bdobb socket ticket v1")`; `target` is the canonical path and
  query `socketTarget()` returns: `/news/ws/news`, `/grid/live_grid_ws` (no query), or
  `/grid/ta_chart_ws?<query re-serialised by the /grid/ta_chart grammar>`.
- The ticket is the last parameter, spelled literally, once; the request carries no
  `Authorization` and `Origin: <previewOrigin>`. Each nonce is admitted once. Tickets are off
  until `previewOrigin` is set.

## Configuration

- `gateway.env` (from `gateway.env.example`, `chmod 600`): `GATEWAY_TOKEN` (32–256 base64url;
  the web preview's `BACKEND_GATEWAY_TOKEN`), and `OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD`,
  the same pair as in `credentials.env` (repeated so the gateway never loads provider keys).
- `gateway-config/settings.json` (from `funnel-gateway/settings.example.json`, read-only bind):
  `origin` (`https://openbq.<tailnet>.ts.net:10000`), `previewOrigin`, `stateDir`
  (`/var/lib/bdobb/state` to turn `/state` on), the budgets, and `rssOrigin`/`rssAddress`/`feeds`
  (both-or-neither; feeds need them), and `liveGrid` (`true` when the `live` profile runs). An unknown key, including Rita's `ritaOrigin`,
  `ritaAddress` and `socksProxy`, is refused at startup.
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
docker compose --profile web up -d            # add --profile live (and "liveGrid": true) for /grid
docker compose --profile web exec funnel-gateway node check-upstreams.mjs  # API pair works, API locked, live-grid and wire answer if on
docker compose --profile web exec funnel-gateway node verify.mjs           # the door's own lock, on the bridge
cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json   # the door opens; the sidecar live-applies it, and a malformed file would kill it
# with the v3 overlay running, swap its file instead:
# cp ts-config/serve-v3-funnel.json ts-config/serve-v3.json.new && jq empty ts-config/serve-v3.json.new && mv ts-config/serve-v3.json.new ts-config/serve-v3.json
docker compose --profile web exec -e GATEWAY_URL=https://openbq.<tailnet>.ts.net:10000 funnel-gateway node verify.mjs
```

`git checkout ts-config/serve.json` and a sidecar restart close the door again. Then test from a
device off the tailnet. Neither preflight queries a quote, subscribes to a feed or prints a credential. Tests: `cd
funnel-gateway && npm ci --ignore-scripts && npm test`.
