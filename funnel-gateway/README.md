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

`/ai` (Rita) is back, off by default and Qwen-only (user ruling 2026-10-20). Its rules live in
`rita-policy.mjs`, not `policy.mjs`, so the vendored contract is unchanged: the door forces
`ritaModel` on every query, drops `urls` and `documents` and blanks every nested `url` (Rita
fetches those server-side, from inside the stack's network), and forwards to
`openbq-rita-door` (`docker-compose.v6.yml`), a second Rita that holds no paid provider key and
will not start unless `OPENAI_BASE_URL` names a non-OpenAI (the Spark's) endpoint. An item's
`content` that is itself a fetchable URL is blanked too (Rita hands inline media to her AI SDK).

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
| `/api/widgets.json`, `/api/apps.json` | GET | openbq-api's root documents with the Basic pair injected; no query; bodies up to 16 MiB (every other route: 2 MiB), gzipped for a caller that accepts gzip |
| `/ref/widgets.json`, `/ref/apps.json` | GET | the reference backend's root documents, keyless (no credential is injected); no query; bodies up to 16 MiB, gzipped for a caller that accepts gzip |
| `/ref/agents.json`, `/ref/bundle.apps.json`, `/ref/market-examples.apps.json`, `/ref/assets/bdobb-logo.svg` | GET | the four other exact documents the reference serves with a dot in the path; no query; nothing else dotted passes |
| `GET /ref/<path>` | GET | the reference's other routes, keyless, under the same structural bounds as `/api/api/v1` (lowercase segments, no dot, no `%`, bounded query, re-serialised); any `omni*` segment at any depth is refused |
| `/api/api/v1/**` | GET | under the shape bounds (lowercase route ≤ 200 chars, ≤ 40 query pairs, name grammar, ≤ 1024-char values, no control characters, ≤ 4096 chars leaving), query re-serialised |
| `/api/api/v1/calendar/trading` | GET | only `exchange=<MIC>&year=1990..2040` |
| `/news/api/news?feed_id=<id>&limit=<1-50>` | GET | rss-ticker's history page for **one approved feed id**; no credential |
| `/news/ws/news` | GET + Upgrade | the wire's socket (below); `503` until `feeds` names a feed |
| `/state/<digits>` | GET | the user's saved files `{files: {name: text}}` |
| `/state/<digits>/<file>` | PUT, DELETE | one of the app's JSON stores (`policy.mjs` `stateFile`); 256 KiB a file, 2 MiB and 200 files a user; `application/json` only |
| `/grid/widgets.json`, `/grid/apps.json` | GET | live-grid's root documents with the Basic pair; no query. A `404` from an older live-grid is relayed as a bare `404` (optional documents) |
| `/grid/live_grid`, `/grid/symbol_meta` | GET | the quote grid's REST seed and its per-symbol metadata; `symbol` only, a comma list |
| `/grid/series`, `/grid/chart` | GET | the bars, raw and as a figure; `symbol` (one), `interval`, `start`, `end`, `provider` (`kdb`/`eodhd`), plus `theme` (`light`/`dark`) on `chart` alone |
| `/grid/ticks` | GET | the kdb tick cache's newest ticks for one symbol; `symbol` (one), `limit` (1–1000) |
| `/grid/ta_chart` | GET | the tick chart; `symbol` (one), `interval`, `source` (`local`/`eodhd`), `macro`, `indicators`, `anchor`, `start`, `end`, `theme`; `provider` is **not** mapped |
| `/grid/ws_ticket?target=<socket>` | GET | the desktop app's socket ticket (below): `Origin` must be a desktop origin (else `403`), `target` one `/grid` socket `socketTarget()` accepts (else `404`); answers `{"ticket": …}`, `no-store`; `503` while `liveGrid` is off. A ticket refused at the upgrade for load (`429`, `503`) is not spent |
| `/grid/live_grid_ws` | GET + Upgrade | the quote grid's socket, no query; every params frame re-validated (below) |
| `/grid/ta_chart_ws` | GET + Upgrade | the tick chart's push-only socket; its **query is its subscription** (the `/grid/ta_chart` grammar) |
| `/grid/subscriptions` | GET | live-grid's Subscriptions page, **the one route served without the token** (a frame cannot send one): exact path, no query, no body, this Host; HTML from memory after one fetch, with its own CSP; a failed fetch is held 5 s before the next dial. Only while `liveGrid` is on: off, the page is behind the lock like every path (`401` without the token, `503` with it). The page then asks BDOBB for the credential (`openbb-connect` → `openbb-auth`) |
| `/grid/api/subscriptions` | GET, POST | the watchlist behind the lock; POST takes `{"symbol": …}` (JSON, ≤ 1 KiB, one-symbol grammar), the body rebuilt from the validated symbol |
| `/grid/api/subscriptions/<symbol>` | DELETE | remove one symbol (one-symbol grammar, `^` literal) |
| `/grid/**` with `liveGrid` off | — | `503` (REST and sockets) after the route rules pass; an unmatched `/grid` path is still `404` |
| `/ai/agents.json` | GET | with `rita` on: Rita's document, its model choice narrowed to `ritaModel` and `file-upload` off; `502` if malformed |
| `/ai/v1/query` | POST | with `rita` on: Rita's query (JSON, ≤ 1 MiB) rewritten by `rita-policy.mjs`, her `text/event-stream` relayed as it arrives (5 min, 16 MiB). `X-Rita-Principal: github:<id>` (the web layer's user; absent = the desktop's bucket) gets one turn at a time and `ritaPerHour` queries an hour (120; one per tool round); two turns at a time in all. `429` past a limit, `400` for a malformed body or principal. No caller header reaches her |
| `/ai/v1/feedback` | POST | with `rita` on: a feedback vote (JSON, ≤ 64 KiB) rebuilt by `rita-policy.mjs` from its six fields and posted to Rita's `/v1/feedback`, with `X-Rita-Principal` only when the caller's is `github:<id>`. Charged to `ritaPerHour` like a query; takes no turn slot. `204` relayed; `400` malformed, `413` too large, `429` past the hour, `502` if she refuses |
| `/mcp` | POST | with `mcp` on: one JSON-RPC message (≤ 1 MiB) to `openbq-mcp`, filtered by `mcp-policy.mjs` -- the protocol's own methods, the read-only discovery tools and `call_tool`; never `install_skill`, `run_pipeline`, or through `call_tool` those, itself or the TMX file viewers (they fetch any URL), nor a `call_tool` whose arguments -- any string, and each comma-separated piece of one -- parse as a fetchable URL off `https://` `sec.gov`, `congress.gov`, `govinfo.gov` or `esmis.nal.usda.gov` (the Congress text fetchers check only a substring). Its JSON or event-stream answer is relayed (8 MiB, 2 min) with `Mcp-Session-Id`, and a session answers only the `X-Preview-Principal` that opened it (else `404`, so the client re-initializes). `mcpPerHour` (600) messages per user an hour; `maxConcurrent` in all (a slot is freed when the caller leaves, though openbq-mcp may finish the call: the hourly cap bounds that) |
| `/ai/**` | — | with `rita` off: 404 (POST 405), as at every earlier tag. With it on, anything but the two routes above (her `/v1/generate/*` included) is 404 |
| `/ref/live_grid_ws` | WebSocket | the reference's live grid, keyless: the token plus `Origin` = `origin`, or a single-use 30 s ticket (5 s of signer clock skew tolerated) plus `Origin` = `previewOrigin` (tickets off while unset); no query, no subprotocol; every frame must be `{"params":{"symbol":"A,B"}}` (rebuilt before it is forwarded) or the socket closes; `maxSockets`, no lifetime (a 30 s ping; a missed pong closes it), 10 s to the first frame |
| any other WebSocket upgrade | — | 401 without the token, else 403 (foreign Origin) or 404 |
| everything else | — | 404 |

Caps (settings): `maxConcurrent` (8, ≤ 32) and `maxSockets` (4, ≤ 32, shared by `/news/ws/news`,
`/ref/live_grid_ws` and the `/grid` sockets). There is no daily vendor cap and no per-minute request budget (removed
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

**Nothing is metered.** No route, frame or push spends a budget: there is no daily vendor cap and
no per-minute budget. EODHD's own limits (the plan's daily calls, 50 streamed symbols per key)
still apply, and a request EODHD refuses surfaces as the upstream's error.

**Frame cap.** `FRAME_CAP = 60` client frames per `live_grid_ws` socket, hard-coded. `ta_chart_ws`
pushes are not capped: a tick chart streams while it is open. Both directions are bounded at
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
- **The desktop app** (V10-P1, user ruling 2026-10-15). Its webview socket cannot carry the
  Bearer header either, so before every connect it asks `GET /grid/ws_ticket?target=<target>`
  with the Bearer header and its webview `Origin`. The gateway mints the same ticket shape,
  signed over `"<expiry>.<nonce>.<Origin><target>"`, and admits the socket with that same
  `Origin` and no `Authorization`. A preview ticket (signed over `<target>`, which begins with
  `/`) never verifies as a desktop ticket, nor the reverse. Desktop tickets need no
  `previewOrigin`. The gateway logs neither the ticket nor the token.

## Configuration

- `gateway.env` (from `gateway.env.example`, `chmod 600`): `GATEWAY_TOKEN` (32–256 base64url;
  the web preview's `BACKEND_GATEWAY_TOKEN`), and `OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD`,
  the same pair as in `credentials.env` (repeated so the gateway never loads provider keys).
- `gateway-config/settings.json` (from `funnel-gateway/settings.example.json`, read-only bind):
  `origin` (`https://openbq.<tailnet>.ts.net:10000`), `previewOrigin` (the web preview's portless HTTPS origin, to turn socket tickets on; unset leaves them off), `stateDir`
  (`/var/lib/bdobb/state` to turn `/state` on), the caps (`maxConcurrent`, `maxSockets`), `rssOrigin`/`rssAddress`/`feeds`
  (both-or-neither; feeds need them), the table keys (`tableService`, `tableDesktopPrincipal`,
  `ssrmRoutes`, `tableTimeoutMs`, `ssrmTimeoutMs`; see [managed tables](../table-service/README.md)) and `liveGrid`
  (`true` when the `live` profile runs), and Rita's `rita` (`true` to serve `/ai`; needs the v6
  overlay's `openbq-rita-door` and a `rita-door.env` from `rita-door.env.example`), `ritaModel`
  (required with it, an `openai:` model, e.g. `openai:qwen3.6-35b`) and `ritaPerHour`. An unknown
  key, including the old tailnet Rita's `ritaOrigin`, `ritaAddress` and `socksProxy`, is refused
  at startup, and so is `ritaModel` or `ritaPerHour` without `rita`. `mcp` (`true` to serve `/mcp`; needs the v6 overlay's `openbq-mcp`) and `mcpPerHour`; `check-upstreams` then needs `openbq-mcp` to open a session. `check-upstreams` refuses a
  door Rita that offers any model other than `openai:` or `ollama:` ones.
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
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web up -d   # add --profile live (and "liveGrid": true) for /grid
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node check-upstreams.mjs  # API pair works, API locked, live-grid answers and is locked, wire answers, if on
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec funnel-gateway node verify.mjs           # the door's own lock, on the bridge
cp ts-config/serve-v3-funnel.json ts-config/serve-v3.json.new && jq empty ts-config/serve-v3.json.new && mv ts-config/serve-v3.json.new ts-config/serve-v3.json   # the door opens; the sidecar live-applies it, and a malformed file would kill it
# a base stack without the v3 overlay swaps its own file instead:
# cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web exec -e GATEWAY_URL=https://openbq.<tailnet>.ts.net:10000 funnel-gateway node verify.mjs
```

`git checkout ts-config/serve.json` and a sidecar restart close the door again. Then test from a
device off the tailnet. Neither preflight queries a quote, subscribes to a feed or prints a credential. Tests: `cd
funnel-gateway && npm ci --ignore-scripts && npm test`. In Docker, mount the repo root (`-v "$PWD:/r" -w /r/funnel-gateway`), because the version test reads `../docker-compose.yml`.
