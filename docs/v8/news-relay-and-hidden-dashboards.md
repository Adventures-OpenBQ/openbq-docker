<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# v8: the web News relay (R3) and the hidden docks dashboard (R6)

Survey for the BDOBB v8 carry (BDOBB clean `claude/clean-v8` at v7.0.0 `8eb9ff6`, rulings in its
`docs/releases/v8-assembly.md`, commit `c4908fd7`). Donor stack: bdobb-dev/openbb-docker **v8.0.3**
(`775354f`, read-only clone). Donor client: bdobb-v2 **v8.1.2**, commit `a7772b2b` "feat(web): the news
relay and socket tickets at 8.0.2".

Summary (after the user's rulings of 2026-10-11 on the first survey):

- **R3 is implemented** as the opt-in `web` compose profile: `funnel-gateway` (ported from the donor
  with `/api`, `/state` and `/news` only, no `/ai`) and `rss-ticker`, plus `ts-config/serve-funnel.json`.
  Section 4.
- **R6 is implemented** in both of BDOBB's Workspace modes: key mode (`v3/openbq_settings.py`) and
  login mode (`workspace/patches/004-system-dashboard.patch` for the source-built Workspace/Lite).
  The contract is the same in both and covers PUT and DELETE with revision checks. Section 3.
- Section 2 records where the repo stood before this work. The v8 line is `release/v7` (v7.0.0)
  merged into `main`; the user approved that base (R6d).

## 1. What the donor v8.0.3 gateway does

### Services (`docker-compose.yml`)

| Service | Image | Role for `/news` |
|---|---|---|
| `funnel-gateway` | `openbq-funnel-gateway:8.0.0`, built from `./funnel-gateway` (Node, `ws`) | The public door. It runs under `profiles: ["web"]`, is published only on Funnel port **10000** through `ts-config/serve-funnel.json` (or `serve-v3-funnel.json` with the v3 overlay), and is `read_only` with `cap_drop: [ALL]`, 512 MB and 64 pids. It reads the bind mount `./gateway-config/settings.json` and writes only the `gateway-state` volume. |
| `rss-ticker` | `openbq-rss-ticker:8.0.0` (built locally from `rss-ticker/`, the vendored rss-feedhandler v8.3.1 source: `docker compose --profile web build rss-ticker`) | A shared feed pool that is not tied to any user. It polls the union of the subscribed feed URLs, streams new articles tagged by `feed_id` over `/ws/news`, and pages history at `/api/news`. It has **no authentication**, so the only access control is who can reach it. Serve publishes it on tailnet port `:8088`, and it is never funneled. Its config is `rss-ticker-config/config.yaml` (`retention_days`, `default_poll_interval_s`, `max_concurrent_polls`, `bind_host`, and an optional `live_tv` channel list that turns on the Live TV widget in its `/widgets.json`), and it keeps its data in the `rss-ticker-data` volume. |
| `openbb-api` | `openbb-local:8.0.3` | The `/api` upstream. Not part of `/news`. |

### Env and settings

- `gateway.env`: `GATEWAY_TOKEN`, the machine token (32–256 base64url). The same value is the Vercel
  project's `BACKEND_GATEWAY_TOKEN`.
- `api-auth.env`: the Basic pair the gateway injects toward openbb-api.
- `gateway-config/settings.json` (`funnel-gateway/config.mjs` `SETTINGS_KEYS`): `origin`,
  `previewOrigin`, `stateDir`, `maxConcurrent`, `maxSockets`,
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
too. The gateway caps concurrency (`maxConcurrent`) and sockets (`maxSockets`); it has no daily
or per-minute budget (`quoteDailyLimit` and `requestsPerMinute` are refused at startup by name).

| Route | Rule | Upstream |
|---|---|---|
| `GET /news/api/news?feed_id=<id>&limit=<n>` | Only those two keys. `feed_id` is a positive integer that must be one of `feeds`' values. `limit` is 1–50, and an out-of-range value is refused rather than clamped (`policy.mjs` `upstreamPath`). | `GET <rssOrigin>/api/news?...`, without the caller's headers. The response must be JSON, up to 2 MB, and is answered with a 12 s timeout. |
| `GET /news/ws/news` (WebSocket upgrade, no query) | `socketTarget()` accepts it. Admission is by Bearer + Origin = `origin`, **or** by a socket ticket + Origin = `previewOrigin` (below). `maxSockets` (default 4) is the only socket cap. 503 if `feeds` is empty. | `wss://<rssOrigin>/ws/news` (`server.mjs` `connectNews`), opened only after the client's single frame passes `newsSubscription`. 64 KiB frames, no compression, no redirects. No lifetime (a 30 s ping closes a socket whose client stops answering), and the first frame must arrive within 10 s. |
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

## 3. R6: the hidden docks dashboard (key mode and login mode)

### Contract (identical in both modes)

| Route | Request | Answer |
|---|---|---|
| `GET /pro/dash/sync/system/docks` | — | 200 `{"dashboard": <record>}`, or `{"dashboard": null}` when none is stored |
| `PUT /pro/dash/sync/system/docks` | body `{"revision": <int ≥ 0>, "content": {…}}`, exactly these two keys, ≤ 5 MB | 200 `{"success": true, "dashboard": <record>}`. **409** `{"detail", "dashboard": <stored record>}` when the stored revision is higher; an equal revision is accepted. 400 malformed, 413 over 5 MB. |
| `DELETE /pro/dash/sync/system/docks?revision=<int ≥ 0>` | exactly one `revision` query parameter, ASCII digits, nothing else | 200 `{"success": true}`, also when nothing was stored. **409** with the stored record when its revision is higher. 400 when `revision` is missing, repeated, non-integer or joined by another parameter. |
| `/pro/dash/sync/system/<other>` | — | 404 (only `docks` is reserved) |

`<record>` is `{"id": "docks", "hidden": true, "revision": n, "content": {…}, "created_date", "updated_date", "created_by", "creator": true, "is_shared": false}`. Dates are server-set ISO-8601 UTC strings with a `Z` suffix.

Semantics:

- **The flag is `hidden: true`.** The docks is never listed by `GET /pro/dash/sync/owned`, by the
  root folder or, in login mode, by `GET /pro/dash/sync` or `/validate-and-sync` (the Workspace web
  app's own listings). `content` is kept exactly as sent.
- **The reserved id is `docks`**, the same as BDOBB's `DOCKS_ID`. `POST /pro/dash/sync` cannot reach
  it in either mode.
- **There is one docks per account**: one per Basic credential in key mode, and one per Workspace
  user in login mode (unique on owner and id).
- **The newest revision wins.** `revision` is the client's last docks edit time in epoch ms (ruling
  R6a). A PUT or DELETE with an older revision answers 409 and carries the winner, which the client
  should take.
- **Auth.** Key mode uses the API's Basic credential and answers 404 when `OPENBB_API_AUTH` is off.
  Login mode uses `Authorization: Bearer <access_token from POST /pro/login>`, as BDOBB already
  sends; a missing token is refused.

The client must:

- leave the docks out of the ordinary `/owned` + `POST /pro/dash/sync` plan, so that
  `planDashboardSync`'s `uploadNew` skips it;
- sync it through these routes, in both modes;
- send the same `revision` on PUT and DELETE;
- take the dashboard returned in a 409.

### Key mode (`v3/openbq_settings.py`)

The docks is stored in the credential's dashboards file under the key `docks`, as a record with
`hidden: true` and `revision`. Tests: `v3/tests/test_openbq_settings.py`, with 37 docks cases among
68 in total. The live check is `scripts/verify-settings.py`.

### Login mode (`workspace/patches/004-system-dashboard.patch`)

The patch targets OpenBB-finance/workspace at the pinned `be00e95` and applies after patches
001–003 with `patch -p1`, as the workspace README describes. It adds:

- the `SystemDashboard` model, table `system_dashboard`: `owner_uuid` (FK `user.uuid`, cascade),
  `system_id`, `revision` (BigInteger), gzip-JSON `content`, dates, and a unique constraint on
  `(owner_uuid, system_id)`;
- Alembic revision `9b1d0c5e7a42`, following the pinned head `0d4a342f4c26` and guarded against an
  existing table;
- the three routes in `routers/pro/dash.py`.

The docks lives in its own table, so none of Workspace's dashboard listings, sharing or versions
code can see it.

Verification, run against the pinned upstream fetched into a scratch directory:

- A fresh `assemble.sh` followed by patches 001–004 applies cleanly.
- `alembic upgrade head` runs through the whole chain on SQLite, the Lite default.
- The backend ran under the Lite image's runtime environment with Redis, using the image's pinned
  Python packages, slowapi at `d3442b2`, and `scripts.init_users`.
- `workspace/scripts/verify-system-dashboard.py` signs in through `/pro/login` as BDOBB does. It
  passed all 14 checks, which include:
  - the owned list and the full `/pro/dash/sync` leaving the docks out;
  - 409s on a stale PUT and on a stale DELETE;
  - a 400 for DELETE without a revision;
  - a 404 for an unreserved id.
- A two-account check showed that each account has its own docks and that an ordinary dashboard
  is still listed.
- All of these were repeated with `dash.py` compiled by Cython, as the Lite image builds it.
- `workspace/tests/test_patches.py` checks the patch notices, the README's apply list and the
  migration's parent.

Not run: the upstream backend's own pytest suite, which needs MySQL testcontainers and Docker, and
a full `docker build` of the image. Docker has no daemon here.

## 4. R3: the gateway, as the opt-in `web` profile

### What was ported

The source is donor `funnel-gateway/` at v8.0.3 (`775354f`), Apache-2.0, same copyright holder. The
following files were ported into `funnel-gateway/`:

- `policy`, `config`, `server`, `entry`, `healthcheck`, `verify` and `check-upstreams` (`.mjs`);
- `Dockerfile`, `package.json` and `package-lock.json` (`ws` 8.21.3);
- `settings.example.json`;
- the tests `gateway`, `policy` and `tls` (`.test.mjs`).

Removed, as ruled:

- `/ai/agents.json` and `POST /ai/v1/query` (Rita), with `postRita`, `handleQuery`, `ritaOptions`
  and the SOCKS5 dialer (`socksConnect`, `socks.test.mjs`);
- the settings `ritaOrigin`, `ritaAddress` and `socksProxy`, which are now refused as unknown keys.

openbq-specific changes:

- The upstream is `http://openbq-api:6900`.
- The gateway reads only `gateway.env`: `GATEWAY_TOKEN` plus the API's Basic pair repeated from
  `credentials.env`, so it never loads provider keys.
- `check-upstreams.mjs` also requires the API to answer 401 without the pair. Basic auth is optional
  on openbq-api, and the door must not open on an unlocked API.

Compose (`docker-compose.yml`) puts both services under `profiles: [web]`:

| Service | Image | Notes |
|---|---|---|
| `rss-ticker` | built from `rss-ticker/`, tagged `openbq-rss-ticker:8.0.0` | Config from `rss-ticker-config/config.yaml`; data in the `rss-ticker-data` volume. |
| `funnel-gateway` | built, `openbq-funnel-gateway:8.0.0` | `read_only`, uid 1000, `cap_drop: ALL`, 512 MB, `gateway-state` volume, `gateway-config/` bind mounted read-only. |

Neither service publishes a host port. Serve (`ts-config/serve-funnel.json`):

- `:443` → openbq-api, tailnet only;
- `:10000` → funnel-gateway, the only port with `AllowFunnel` (8443 stays the episode 3 reference's);
- `:8088` → rss-ticker, tailnet only.

The default `ts-config/serve.json` publishes the same ports minus `:10000`, and carries no `AllowFunnel` at all (`tests/test_web_profile.py` checks both). Its `:8088` answers 502 until the `web` profile runs. To open the door, write `serve-funnel.json` to `serve.json.new`, check it with `jq empty`, and `mv` it over `serve.json`: the sidecar live-applies the file, and a malformed one would kill it. With the v3 overlay, the pair is `serve-v3.json` (443, the reference on 8443, 8088) and `serve-v3-funnel.json` (the same plus `:10000`), so the reference and the door run on one node. `funnel-gateway/README.md` has the full port table.

### Gateway contract the BDOBB web layer codes to

- Every HTTP request carries `Authorization: Bearer <GATEWAY_TOKEN>`. `Host` is the `origin`, and
  an `Origin`, if present, equals it.
- Routes:
  - `GET /api/widgets.json` and `GET /api/apps.json`, with no query;
  - `GET /api/api/v1/**`, under the structural bounds;
  - `GET /api/api/v1/calendar/trading?exchange=<MIC>&year=<1990..2040>`;
  - `GET /news/api/news?feed_id=<approved id>&limit=<1..50>`;
  - the WebSocket `/news/ws/news`, which takes no query;
  - `GET /state/<digits>`, and `PUT` or `DELETE /state/<digits>/<stateFile>`;
  - `GET /_gateway/health`.
- Anything else answers 404, including all of `/ai`.
- The socket accepts one text frame, `{"subscribe":[{"url":"https://…"}, …]}`, with 1–50 unique
  urls. It is rebuilt from the approved urls; the socket has no lifetime, and a 30 s ping closes it once the client stops answering.
- Ticket: `<13-digit expiry ms>.<22-char base64url nonce>.<43-char base64url HMAC-SHA256>`.
  - Key: `K = HMAC-SHA256(GATEWAY_TOKEN, "bdobb socket ticket v1")`.
  - Signed message: `"<expiry>.<nonce>.<target>"`, where `target` is `/news/ws/news`.
  - A ticket lasts 30 s and works once.
  - It goes last on the URL: `wss://<origin>/news/ws/news?ticket=<ticket>`.
  - The request carries no `Authorization` header, and `Origin` must equal `previewOrigin`.
- Config keys in `gateway-config/settings.json`:
  - `origin`, `previewOrigin` and `stateDir`;
  - the caps `maxConcurrent` and `maxSockets`;
  - `rssOrigin`, `rssAddress` and `feeds`.
- `gateway.env` holds `GATEWAY_TOKEN`, `OPENBB_API_USERNAME` and `OPENBB_API_PASSWORD`.

### The policy header and BDOBB's vendored copy

The `policy.mjs` docblock names openbq-docker as the source and cites `bdobb-dev/openbb-docker
v8.0.3 (775354f)` as the donor. At this branch its sha256 is
`dfa61ddf8872fe83d1447a62ed2347fe58c6509186e8f3772372d209b8e0bfd0`, so BDOBB's vendored first line
would be:

```
// vendored from openbq-docker v8.0.0 funnel-gateway/policy.mjs sha256:dfa61ddf8872fe83d1447a62ed2347fe58c6509186e8f3772372d209b8e0bfd0
```

The admission logic matches the client's v8.1.2 `web/policy.mjs`, which is the donor's, except that
`upstreamPath` no longer admits `/ai/agents.json`. A scratch check confirmed the match:

- both policies give the same answers for `/api`, `/news`, `/state`, socket targets, the subscription
  frame and `stateFile`;
- a ticket signed by the client's own `socketTicket` opens this gateway's socket once and is refused
  on reuse.

### Tests

- `cd funnel-gateway && npm ci --ignore-scripts && npm test`: 47 tests pass, steadily.
- `pytest tests` covers the profile, the absence of host ports, both Serve configs and the
  placeholders in the examples.
- `docker compose --profile web config --quiet` validates, and the default set of services is
  unchanged.
- CI (`public-content.yml`) now runs both.
- The donor's ticket tamper test flipped the signature's last base64url character. That character
  carries padding bits only, so the test failed about one run in sixteen. It now flips a character
  inside the signature. This is a test fix only: the nonce is what is single-use, so a ticket whose
  padding bits differ cannot replay one already admitted.

### Operating notes and what is still open

- **Reaching rss-ticker.** The gateway dials it by its tailnet name (`rssOrigin`, port 8088) at a
  pinned tailnet IPv4 (`rssAddress`), as the donor does. This works only if the Docker host routes
  the bridge into the tailnet; `funnel-gateway/README.md` has the one-command check. Without that
  route, `/news` stays off (404/503) and `/api` and `/state` still work.
- **One image digest is not pinned.** `node:22-alpine` is referenced by tag. The rss image is not
  pulled: compose builds it locally from `rss-ticker/` as `openbq-rss-ticker:8.0.0`.
- **Not built or run.** Docker has no daemon here, so the gateway image was not built and no
  container was run.
- **rss-ticker runs without the door.** Naming the service starts it alone, with no `gateway.env`
  or `gateway-config/`: `docker compose up -d rss-ticker` (check with `docker compose config -q rss-ticker`).
