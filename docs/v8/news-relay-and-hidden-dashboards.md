<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# v8: the web News relay (R3) and the hidden docks dashboard (R6)

Survey for the BDOBB v8 carry (BDOBB clean `claude/clean-v8` at v7.0.0 `8eb9ff6`, rulings in its
`docs/releases/v8-assembly.md`, commit `c4908fd7`). Donor stack: bdobb-dev/openbb-docker **v8.0.3**
(`775354f`, read-only clone). Donor client: bdobb-v2 **v8.1.2**, commit `a7772b2b` "feat(web): the news
relay and socket tickets at 8.0.2".

Summary:

- **R6 is implemented** here (`v3/openbq_settings.py`, key-mode routes). Contract below.
- **R3 is not implemented.** openbq-docker has no gateway layer at all, so the donor's `/news` relay has
  nothing to sit in, and porting it means two new services and images plus a public Funnel port. That
  needs the user's decision; the options are at the end.

## 1. What the donor v8.0.3 gateway does

### Services (`docker-compose.yml`)

| Service | Image | Role for `/news` |
|---|---|---|
| `funnel-gateway` | `openbb-funnel-gateway:8.0.3`, built from `./funnel-gateway` (Node, `ws`) | The public door. It runs under `profiles: ["web"]`, is published only on Funnel port **8443** through `ts-config/serve-funnel.json`, and is `read_only` with `cap_drop: [ALL]`, 256 MB and 64 pids. It reads the bind mount `./gateway-config/settings.json` and writes only the `gateway-state` volume. |
| `rss-ticker` | `ghcr.io/artcashin/rss-feedhandler:8.0.0` (prebuilt, external) | A shared feed pool that is not tied to any user. It polls the union of the subscribed feed URLs, streams new articles tagged by `feed_id` over `/ws/news`, and pages history at `/api/news`. It has **no authentication**, so the only access control is who can reach it. Serve publishes it on tailnet port `:8088`, and it is never funneled. Its config is `rss-ticker-config/config.yaml` (`retention_days`, `default_poll_interval_s`, `max_concurrent_polls`, `bind_host`), and it keeps its data in the `rss-ticker-data` volume. |
| `openbb-api` | `openbb-local:8.0.3` | The `/api` upstream. Not part of `/news`. |

### Env and settings

- `gateway.env`: `GATEWAY_TOKEN`, the machine token (32–256 base64url). The same value is the Vercel
  project's `BACKEND_GATEWAY_TOKEN`.
- `api-auth.env`: the Basic pair the gateway injects toward openbb-api.
- `gateway-config/settings.json` (`funnel-gateway/config.mjs` `SETTINGS_KEYS`): `origin`,
  `previewOrigin`, `stateDir`, `quoteDailyLimit`, `requestsPerMinute`, `maxConcurrent`, `maxSockets`,
  `ritaOrigin`/`ritaAddress`, `socksProxy`, `rssOrigin`/`rssAddress` and `feeds`.
  - `rssOrigin` + `rssAddress` (`config.mjs` ~L100–110) give rss-ticker's tailnet HTTPS name (default
    port 8088) and its pinned tailnet IPv4. Set both or neither. With neither, the `/news` family is off.
  - `feeds` (`config.mjs` ~L111–135) is `{ "<https feed url>": <rss-ticker feed id> }`, one-to-one, at
    most 50 entries. It is the only allowlist. When it is empty, the history route answers 404 and the
    socket answers 503.
  - `previewOrigin` turns socket tickets on. It is the one Origin besides the gateway's own that a
    WebSocket may arrive from.
  - `GATEWAY_UID`/`GATEWAY_GID` set the compose user.

### Routes (`funnel-gateway/policy.mjs`, `server.mjs`)

Every HTTP request must carry exactly one `Authorization: Bearer <GATEWAY_TOKEN>` header, compared in
timing-safe form. `Host` must equal `origin`, and an `Origin` header, if present, must equal `origin`
too. The gateway meters requests per minute (`requestsPerMinute`) and caps concurrency
(`maxConcurrent`).

| Route | Rule | Upstream |
|---|---|---|
| `GET /news/api/news?feed_id=<id>&limit=<n>` | Only those two keys. `feed_id` is a positive integer that must be one of `feeds`' values. `limit` is 1–50, and an out-of-range value is refused rather than clamped (`policy.mjs` `upstreamPath`). | `GET <rssOrigin>/api/news?...`, without the caller's headers. The response must be JSON, up to 2 MB, and is answered with a 12 s timeout. |
| `GET /news/ws/news` (WebSocket upgrade, no query) | `socketTarget()` accepts it. Admission is by Bearer + Origin = `origin`, **or** by a socket ticket + Origin = `previewOrigin` (below). `maxSockets` (default 4) applies, and an admission costs 6 budget units. 503 if `feeds` is empty. | `wss://<rssOrigin>/ws/news` (`server.mjs` `connectNews`), opened only after the client's single frame passes `newsSubscription`. 64 KiB frames, no compression, no redirects. Lifetime 240 s, and the first frame must arrive within 10 s. |
| Others at v8.0.3 (not `/news`) | `/api/widgets.json`, `/api/apps.json`, `/api/api/v1/**` (structural bounds), `/api/api/v1/calendar/trading`, `/ai/agents.json`, `POST /ai/v1/query`, `/state/<id>[/<file>]`, `/_gateway/health` | openbb-api, Rita, the state volume |

`newsSubscription(data, config)` applies these rules to the client's frame:

- Exactly one frame, of the form `{"subscribe":[{"url":"https://…"},…]}`, with 1–50 entries, unique
  string urls and no other keys.
- Unapproved urls are dropped. If none is left, the socket closes.
- The gateway forwards a newly built `{"subscribe":[{"url":…}]}`, never the caller's own object.

### Socket ticket (`policy.mjs`, identical in donor and client)

- Format: `<expiry ms, 13 digits>.<nonce: 16 random bytes, base64url, 22 chars>.<HMAC-SHA256, base64url, 43 chars>`.
- Key: `HMAC-SHA256(key = GATEWAY_TOKEN, msg = "bdobb socket ticket v1")`.
- Signature: `HMAC-SHA256(key, "<expiry>.<nonce>.<target>")`. The target is the canonical path plus
  query that `socketTarget()` returns. At v8.0.3 the only target is `/news/ws/news`.
- Lifetime 30 s, and an expiry more than 30 s ahead is refused. The gateway keeps admitted nonces until
  they expire, so each ticket works once.
- On the wire: `wss://<gateway>/news/ws/news?ticket=<ticket>`. The ticket must be the **last**
  parameter, spelled literally, and appear exactly once. The request must have no `Authorization`
  header and `Origin: <previewOrigin>`, and the gateway checks the ticket against the URL with the
  ticket removed (`server.mjs` ~L404–429).
- The web layer (bdobb-v2 `web/server.mjs` `/socket-ticket`) signs the ticket after checking the GitHub
  session. The token never reaches the browser.
- Verified: bdobb-v2 v8.1.2 `web/policy.mjs` minus its first `// vendored from` line has sha256
  `127a6b80…2574`, identical to donor `funnel-gateway/policy.mjs` at v8.0.3.

### Preflight and verify

- `check-upstreams.mjs` fetches one history page for an approved feed and does an rss-ticker socket
  handshake.
- `verify.mjs` probes the lock, the Origin rule and the socket route through the public door, and checks
  that malformed `/news/...` requests are refused.

## 2. Where Adventures openbq-docker stands

Checked at `main` (`f3bf3d4`) and `release/v7` (tag v7.0.0, `21f0261`). The v8 branch is `release/v7`
merged into `main` (clean merge, `e58ccb3`). `main` alone stops at the v4 merge and lacks the Workspace
dashboard/app sync.

- **No gateway layer.** There is no `funnel-gateway` or any other Node service, no `.mjs`, no
  `gateway.env`, no `settings.json`, no ticket verifier, and no `/api`, `/state`, `/ai` or `/news` door.
  `git grep` for funnel/gateway/rss/ticket finds only README text saying "Funnel is disabled".
- **No news service.** There is no rss-ticker and no feed pool. The only "news" is ODP's own
  `/api/v1/news/*` provider routes, such as the vendored `v3/yfinance/.../routers/news.py`.
- **Ingress.** `ts-config/serve.json` serves `:443` → `openbq-api:6900` with `AllowFunnel` false.
  `serve-v3.json` adds `:8443` → `openbq-reference:17783` (episode 3), also with Funnel false.
  `workspace/ts-config/serve.json` is for the Workspace Lite companion and is tailnet-only.
- **Compose services.** `docker-compose.yml` has `tailscale`, `openbq-api`, and `workspace` +
  `workspace-tailscale` under `profiles: [workspace]`. `docker-compose.v3.yml` has `openbq-api`,
  `tailscale` and `episode3-demo`.
- **How BDOBB reaches it today.**
  - The desktop app connects to `https://openbq.<tailnet>.ts.net` with the API's own Basic pair. Key
    mode (`v3/openbq_settings.py`) serves `/pro/user`, `/pro/display-settings`, `/pro/dash/sync*` and
    `/pro/user-apps/*` behind that same credential.
  - The **web** build (BDOBB `web/`, env `BACKEND_GATEWAY_ORIGIN` + `BACKEND_GATEWAY_TOKEN`) expects
    the donor gateway contract: Bearer token, `/api/...`, `/state/...` and, with R3, `/news/...` plus
    tickets. **openbq-docker serves none of that.** The clean client's vendored policy says so in its
    header ("vendored from openbb-docker v3.0.1"), and so do its `openbbDocker` pin (v3.0.1) and
    `web/README.md` ("The current private Basic-auth gateway does not implement that contract").
    So the web build has no Adventures backend today for `/api` and `/state` either, not only for
    `/news`.
- **Workspace server.** Two different things carry this name:
  - **Key mode**: `openbq-api`'s own `/pro/*` emulation, which this repo owns.
  - **Login mode**: the source-built official Workspace/Lite under `workspace/`. Its source is upstream,
    pinned in `workspace/source.json` and adjusted by `workspace/patches/*`. The upstream source is not
    in this repo.

## 3. R6, implemented: the hidden docks dashboard (key mode)

The routes are in `v3/openbq_settings.py` and the tests in `v3/tests/test_openbq_settings.py`. The live
check is `scripts/verify-dashboards.py`.

| Route | Request | Answer |
|---|---|---|
| `GET /pro/dash/sync/system/docks` | — | 200 `{"dashboard": <record>}`, or `{"dashboard": null}` when none is stored |
| `PUT /pro/dash/sync/system/docks` | `{"revision": <int ≥ 0>, "content": {…}}`, exactly these two keys, ≤ 5 MB | 200 `{"success": true, "dashboard": <record>}`. **409** `{"detail": …, "dashboard": <stored record>}` when the stored `revision` is greater. An equal revision is accepted. 400 for a malformed body, 413 over 5 MB. |
| `DELETE /pro/dash/sync/system/docks` | — | 200 `{"success": true}`, also when nothing was stored |
| any other `/pro/dash/sync/system/<id>` | — | 404 |
| any other method on the docks route | — | 405 |

`<record>` = `{"id": "docks", "hidden": true, "revision": n, "content": {…}, "created_date", "updated_date", "created_by", "creator": true, "is_shared": false}`.

Semantics:

- **The flag is `hidden: true`** on the stored record, which sits beside `content`, not inside it.
  `GET /pro/dash/sync/owned` never lists a hidden record, and the root folder's adoption ignores it.
  `content` is kept exactly as sent.
- **The reserved id is `docks`**, the same as BDOBB's `DOCKS_ID`. It is not a uuid, so
  `POST /pro/dash/sync` (which takes only uuid keys) can neither write nor delete it. Both attempts
  answer 400.
- **One per account.** The store has one dashboards file per Basic credential, and the docks occupies
  one fixed key in it.
- **The newest revision wins.** `revision` is supplied by the client and compared as an integer. BDOBB
  should send its last local docks edit time in epoch milliseconds, so two devices compare the same
  clock. A losing PUT receives the winner in its 409 body. `updated_date` is still set by the server,
  and `created_date` is kept across PUTs.
- The same lock as the other routes applies: Basic auth, 404 with `OPENBB_API_AUTH` off, CORS
  allow-origin added, atomic write under the one process lock.

What the client must do:

- Leave the docks out of the ordinary `/owned` + `POST /pro/dash/sync` plan, so that
  `planDashboardSync`'s `uploadNew` must skip it.
- Sync it through these routes instead.
- On a 409, take the returned dashboard.

## 4. R3: options for the user (not implemented, stop condition met)

The `/news` relay cannot be ported mechanically. openbq-docker has no gateway to put it in. The
donor's relay needs `rss-ticker` (a new external image) and `funnel-gateway` (a new Node image), and it
is only useful on a public Funnel port, which this repo currently disables by policy. The choices:

1. **Port the whole donor gateway as an opt-in `web` profile.** Add `funnel-gateway/` (policy, server,
   config, verify, check-upstreams, tests; Apache-2.0, provenance to openbb-docker v8.0.3 `775354f`),
   an `rss-ticker` service (`ghcr.io/artcashin/rss-feedhandler:8.0.0` or a pinned digest),
   `gateway.env.example`, `gateway-config/settings.example.json`, `rss-ticker-config/config.yaml.example`
   and `ts-config/serve-funnel.json` (`:8443` → `funnel-gateway:8091`, Funnel on). This gives the web
   build `/api`, `/state` and `/news` together.
   - Approval needed: two new images, the Node toolchain in this repo, and a public Funnel port.
   - Decide whether to keep `/ai` (Rita) out.
   - Decide whether `policy.mjs`'s header should say openbq-docker. The client's `security.test.mjs`
     L637 regex requires `vendored from openbb-docker vX.Y.Z`.
2. **Port only `/news`, without a gateway service:** a tailnet-only rss-ticker plus a news relay inside
   `openbq-api`. **Not viable.** The client contract is Bearer + tickets + Origin = `previewOrigin` on
   a public origin, and openbq-api's middleware is Basic-only HTTP with no WebSocket relay. It would
   still need the rss-ticker image.
3. **Pair the web build with bdobb-dev/openbb-docker v8.0.3** for its gateway, as the client already
   does at v3.0.1. Raise `openbbDocker` to v8.0.3 and vendor its `policy.mjs` (sha `127a6b80…`), with
   no openbq-docker change. This contradicts R3's note that the stack should be an
   Adventures-OpenBQ/openbq-docker release.
4. **Defer the web News relay.** Desktop News talks to an rss-ticker the user runs. The web build
   keeps `socketTarget() === null`.
