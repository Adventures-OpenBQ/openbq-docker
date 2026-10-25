<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v10.0.0 release receipt (2026-10-14)

Gated tree: `e6cb490` (`claude/openbq-docker-v10`). This receipt commit changes only this file. `release/v10` contains `release/v9` = v9.0.0 `e6826b1`, through merge `e6cb490`. User order: "tag openbq-docker v10.0.0 and re-pin bdobb".

## What v10.0.0 adds over v9.0.0

- **The live grid** (Episode 10). The `live-grid` FastAPI sidecar serves a ticking quote grid, `/symbol_meta`, series and charts, and its own `apps.json`. Its history comes from EODHD through `OPENBB_HISTORY_NAMESPACE=eodhd`, so every chart call is metered. Ticks are spooled to the `live-grid-data` volume and replayed exactly once after an outage (user ruling 2026-10-12). Reconnects back off from 1 s to 15 s.
- **The kdb+ tick tier, openbq-kdb 10.0.0.** It is vendored in `v10/kdb/source/` from Adventures-OpenBQ/openbq-kdb at `6d2035b` (tag v10.0.0, re-cut 2026-10-17 with the v10 review's kdb fixes, openbq-kdb #1; first cut `9519bbc`). That tree is byte-identical to the vendored one, path for path and blob for blob. `v10/kdb/source.json` names that commit and the tag `v10.0.0`.
  - The package is this line's `kdb-store/` and `kdb-ws/`, renamed `openbq-kdb` (module `openbq_kdb`, q scripts under `q/`). The ledger section is "Renamed openbq-kdb" in `docs/v10/live-grid-kdb-port.md`.
  - The compose service is `openbq-kdb`, using `${KDB_IMAGE}`, whose default is the maintainer's private, digest-pinned, linux/amd64-only image; others build theirs with `compose.kdb-build.yml`. It runs the repository's `q/startup.q` and `q/persist.q` read-only from `/opt/openbq-kdb`, keeps its tick logs on the `kdb-data` volume, and recovers from a crash by replaying the logs of today and the two days before. A torn log tail (host crash, `ENOSPC`) is cut back to its last whole chunk through a temp file and a rename, and one bad log cannot switch logging off. An append that fails during a run is not applied (live-grid's spool keeps the batch), and the next update cuts the log back before it appends (checked on a real q by `q/tests/test_persist.py`).
- **The `live` compose profile.** `openbq-kdb` and `live-grid` are opt-in and have no host port. `openbq-kdb` and the S3 tier (`rustfs`, `rustfs-init`, `eod-dump`) sit on `live-private` only, an `internal: true` network that `live-grid` also joins; `live-grid` keeps `openbq-internal` for the API and the gateway, so funnel-gateway and openbq-api cannot reach q or RustFS. The default stack is still `openbq-api` plus `tailscale`. The kdb licence comes from `KDB_LICENSE_DIR` (default `./kdb-license`) and is mounted read-only. `compose.kdb-build.yml` builds kdb-x locally.
- **The S3 tier on RustFS 1.0.1** (user ruling: RustFS, not MinIO). It covers bucket init (`scripts/s3_init.py`), `eod-dump` (`scripts/eod_dump.py`) and the lake read-back in a separate `openbq-lake` image (`Dockerfile.lake`, with `openbb-deltalake`). The env files `rustfs.env` and `eod.env` are optional, and the tier fails closed without them. RustFS data is kept on the host (`${RUSTFS_DATA_DIR:-./rustfs-data}`).
- **funnel-gateway 10.0.0.** It adds the `/grid` family behind the `liveGrid` setting, which is off by default, so `/grid` answers 503. That family is Bearer-gated, metered per symbol, capped at 60 frames per socket and admitted with a single-use ticket. It also serves live-grid's Subscriptions page and watchlist API (V10-P5). `funnel-gateway/policy.mjs` gains the `/grid` rules and the grid frame rule. BDOBB 10.0.0 vendors it.
- **BDOBB examples** are synced with `EPISODE=10`. The live-grid example goes to `live-grid/apps.json`.
- **Unchanged from v9.0.0:** `ts-config/`, `Dockerfile.v3` (since the v9 merge, 2026-10-18, the Dockerfile's `v3` stage), `rss-ticker-config/` and the ports: 443 for ODP, 8443 for the Episode 3 reference, 8088 for rss-ticker and 10000 for the gateway (Funnel). `docker-compose.v3.yml` changes only its three image tags, 9.0.0 to 10.0.0 (`openbq-local`, `openbq-episode3-demo`, `openbq-key-maint`).

## Gates run for this receipt (cloud, at `e6cb490`)

| # | Gate | Result |
|---|---|---|
| 1 | `scripts/check-public.py --history HEAD` | PASS, including reachable history |
| 2 | `docker compose config -q`: default; `web` + `workspace`; `live`; with `docker-compose.v3.yml`; v3 overlay + `web`; `compose.kdb-build.yml` + `live` (each `*.env.example` copied to `*.env` in a scratch worktree) | valid |
| 3 | `scripts/verify-app-layouts.py` on all five tracked `apps.json` | passed, no overlaps |
| 4 | `tests` (pytest) | 38 passed, 5 subtests |
| 5 | `v3/tests` | 68 passed |
| 6 | `lanes/tests` | 22 passed |
| 7 | `workspace/tests` | 12 passed |
| 8 | `v9/eodhd/tests` (no EODHD call) | 9 passed |
| 9 | `provider-fixes` (unittest) | 42 OK |
| 10 | `funnel-gateway` `node --test` | 88 pass, 0 fail |
| 11 | `live-grid` (`-m 'not network'`) | 454 passed, 14 deselected |
| 12 | `v10/kdb/source/tests` (openbq-kdb) | 143 passed |
| 13 | `v10/kdb/source/q/tests` | 9 passed |
| 14 | `openbb-deltalake` | 95 passed |
| 15 | `scripts/tests` (moto S3) | 13 passed |

Receipts already recorded on the Mac's real q and Docker: drill A (`38e4958`: kdb SIGKILL for 100 s, 0 dropped, 15,320 replayed, PASS), drills B and C (`b840771`: PASS), and `tick_check.py` (`e384441`: 23 checks, no failures). Those were taken before the openbq-kdb rename: the code was the same, under the old names.

## Docker gates for the Mac, before the tag is pushed

This session has no Docker daemon. As for v9.0.0, these run on the Mac:
- `docker build --target v3 .` (before the v9 merge of 2026-10-18, `docker build -f Dockerfile.v3`);
- `--profile live` build and up with the licence;
- `Dockerfile.lake`;
- `lanes/tests`, `v9/eodhd/tests` and `examples/episode3` in the image;
- `verify-settings.py`, `verify-dashboards.py` and `verify-v4-routes.py` on a local key-mode container;
- `/apps.json` with an `Origin` header;
- `live-grid/scripts/smoke.py` against the `live` profile.

The rest of the Mac-pending list in `docs/v10/live-grid-kdb-port.md` (RustFS init and the eod-dump flush, the two-writer race, and the gateway against live-grid) is carried as it stands.

## Known, carried

Everything carried from v9.0.0 is still carried. Kept as provisional: the `kdb-data` volume and the `KDB_*` variable names keep their pre-rename names, openbq-kdb is version 10.0.0, and live-grid holds the store's root credentials (C6). `DeltaTable.is_deltatable` hangs against S3 (C8).

No image was published and nothing was deployed.

## Re-cut (2026-10-17)

The regression walk re-cut v10.0.0 after the v10 review: 9 Important and 17 Minor findings (D1–D26) and four scoped re-review rounds (Q1–Q5, S1–S4, T1–T2), all fixed. Four defects (L1–L4) were found live on the NAS and fixed:
- one invalid symbol took a whole feed class down;
- a nanosecond feed `t` killed the feed task silently;
- the tasks were unsupervised;
- matplotlib had no writable config directory.

The headline changes:
- **Isolation.** `openbq-kdb` sits on the internal-only `live-private` network, which funnel-gateway and openbq-api cannot reach.
- **The kdb image.** It is overridable through `KDB_IMAGE`; the default is private, digest-pinned and amd64-only, and readers build their own with `compose.kdb-build.yml`.
- **live-grid hardening.** It runs as uid 10001 on a read-only root, after a one-shot `live-grid-perms` job.
- **The spool.**
  - A recurring kdb error quarantines its batch only after backoff.
  - Torn-log refusals (`tlog: `) are never counted toward quarantine.
  - persist.q survives a torn tail and a failed append.
- **eod-dump.** Its catch-up no longer overwrites a complete day.
- **The gateway.** `%5E` subscription DELETEs work; tickets are spent only on a successful upgrade; and `ws_ticket` answers 503 while `liveGrid` is off.

v9.0.0 is carried at `7b54c69`: the rss-ticker and the Rita and MCP images are built from source, and `openbq-mcp` is 10.0.0. The kdb fixes went upstream first and are vendored byte for byte.

**Gates on the final tree:**

| Check | Result |
|---|---|
| `scripts/check-public.py --history HEAD` | PASS |
| `tests` | 68 passed |
| funnel-gateway | 132 of 132 |
| live-grid | 504 passed (14 network tests deselected) |
| openbq-kdb | 144 passed |
| `q/tests` on a real q | 17 passed |
| `scripts/tests` | 15 passed |
| openbb-deltalake | 95 passed |
| `docker compose config -q` (default, `live`, `web`) | valid |

**NAS, production `openbq-episode1` on v10 (2026-10-17):**
- **The `live` profile, with the operator's EODHD key:** kdb starts with its licence on the internal network. A lease of BTC-USD, ETH-USD and AAPL streamed crypto ticks into kdb (1,472–2,582 a minute), and kdb replayed its tick log on restart.
- **The gateway**, with `"liveGrid": true` and `quoteDailyLimit` 3000:
  - `/grid/live_grid` answers 401 without the token and 200 with it;
  - `/grid/symbol_meta` answers 200;
  - `/grid/ws_ticket` issues a ticket for a desktop Origin;
  - a ticketed `/grid/live_grid_ws` streamed 102 frames in 15 s;
  - `/grid/subscriptions` loads anonymously.
- **`nas-verify`:** smoke, app layouts, CFTC, heavy routes, isolation, provider fixes and v4 routes all passed.
- **The BDOBB client regression:** the smoke nine, E05-047, 9 fixtures, the apps walk (46 non-BLS and 5 BLS apps) and OBBject warnings (on a rerun after a 14-minute wait that timed out while the live grid was being exercised) all passed.

**GHCR `10.0.0`**, built for amd64 and arm64:
- `openbq-local` `sha256:8997d236e95d83e84a405781ee6024c84fb4b53189dec13ae3f1201487dd1fd9`, image revision `bd37ed9`. Its inputs are unchanged since.
- `openbq-funnel-gateway` `sha256:dfa8c1e0c4c4aac6de4ae49cf87197a74263fc33167b3560d8bc8c6cd7ff8647`, revision `bd37ed9`. Its inputs are unchanged since.
- `openbq-live-grid` `sha256:f86a6ac9f5a411428fc3774c07c230607829ea24c688abc60cf2037ce93c93ad`, revision `f516641`.
- `openbq-lake` `sha256:224c2f656ad2271e8a0a53c7a9549721b53f9c13c0e547edd6f06b8985f8d409`, revision `f461130`.
- `openbq-table-service` `sha256:55c6dc2ddb5fd06f6edf37bdaa9a56484ba22352d94aa48a85609c7169d9f636`, from BDOBB `d17fe4a` per `table-service/source.lock.json`.
- `openbq-key-maint` `sha256:ba2d3d252680be8c5c804296f29aea2ebde935ad1294dce65df56295728445b5`, the 9.0.0 image re-tagged, unchanged.

Rita and MCP are built locally (`openbq-rita:6.0.0` and `openbq-mcp:10.0.0`, `pull_policy: never`). `latest` was not moved.

## Re-cut (2026-10-18)

v10.0.0 was re-cut again after three user reports on the Live dashboard (the Live Chart did not draw, Subscriptions was blank, Tick History rounded its prices) and the v3–v9 walk's hand-off.

**Live-grid fixes:**
- **Tick History** shows the full time, price and size (`formatterFn: "none"`, no abbreviation). The Live quotes grid gains hidden `Updated (UTC)` and `Stream volume` columns, and a tick now adds its size to the day's volume.
- **Subscriptions** draws on a dark app (Canvas/CanvasText), and its frame address comes from the request when `LIVE_GRID_PUBLIC_URL` is empty (52300fb), so the widget always appears.
- **The Live Chart's `/series`:**
  - EODHD's intraday history ends in `Z` while tick bars are naive UTC, so the seam comparison raised and `/series` answered 502 (765af30).
  - A chart width is now built only from a history source that divides it (user ruling): under a minute, ticks alone; 15m, 30m, 1h and other multiples of 5m from 5m, resampled on the tick grid (EODHD's half-hour-stamped 1h is no longer used); 1m and its multiples from 1m, as one request of at most 120 days (2efa43c, clamped in 455da59).
  - An intraday `/series` defaults to five days (user ruling 2026-10-17).
  - Minutes live-grid was down for are filled at query time (user ruling): US equities from EODHD's real-time `/history` minute bars, crypto from intraday 1m; forex is left unfilled, and ticks win wherever they exist (a5c6ee8).

**Release review** of everything since the 10-17 re-cut (both merges included): 1 Important and 5 Minor findings, all fixed (455da59), and a scoped re-review's 2 Minor follow-ups fixed (f870ea8). The Important one: a 1m `start` far in the past fanned one request out into hundreds of sequential vendor calls; a 1m window is now one request, clamped to the 120 days EODHD accepts. The others: a reversed 1m window raised; the lake read-back path does not gap-fill (documented); resampled bars carry a volume-weighted vwap only when every traded row has one; `Dockerfile.v3` references; and, with `LIVE_GRID_PUBLIC_URL` unset, a browser write to the watchlist is taken only from a loopback host (the Host-derived origin was open to DNS rebinding).

**v9.0.0 is carried at `04ac6ab`** (merges 6cf51a9, a70dc82 and c8aab8a; the second brings the Calendars example's relative ranges, the third Live TV and v7.0.0's CI change back into the chain): local image names in compose and project `openbq-stack`; the v3 image is the Dockerfile's `v3` stage and the gateway's SSRM default comes from `lanes/`; the door relays text/plain and forwards only approved News feeds; key-maint probes EODHD on its own namespace. v10's `/grid` door, `liveGrid` switch and live services are kept as they were.

**Gates on the final tree:**

| Check | Result |
|---|---|
| `scripts/check-public.py` | PASS |
| `tests` | 73 passed |
| `v3/tests` | 68 passed |
| `workspace/tests` | OK |
| funnel-gateway | 122 of 122 (fourth carry) |
| live-grid | 539 passed (14 network tests deselected) |
| key-maint | 230 passed |
| lanes | 89 passed, 1 skipped |

**NAS, production `openbq-stack` on v10 (2026-10-18, from 17:09Z):**
- The copied `openbq-stack_kdb-data` and `openbq-stack_live-grid-data` volumes came up: live-grid replayed a tick its spool held from the old project, and the gap fill rebuilt 1,028 BTC-USD minutes missed while the v3–v9 walk held production.
- `/series` answers 200 at 1s, 1m, 5m, 15m, 30m, 1h and 1d for AAPL and BTC-USD, and at 5m for EURUSD; AAPL's 1h bars now start on the hour.
- `nas-verify`: smoke, app layouts, heavy routes, isolation and provider fixes all passed.
- The Live dashboard, drawn from BDOBB `9ba6a8d1` in browser mode against this stack: Subscriptions lists the watchlist, Tick History shows full prices, and the Live Chart draws five days of AAPL 1m candles. Its long wicks after 20:00 UTC are EODHD's own after-hours prints in the 1m history.
- live-grid at `f870ea8` (after the NAS Docker zvol's inodes were freed by pruning the build cache and week-old unused images): a 1m window from 1900 is one fetch of 120 days, and a reversed one is refused by the provider.
- openbq-api and MCP at `a70dc82`: `nas-verify` passed again, and the served Calendars example opens on its relative ranges (T-1mo/T+2mo, T-MON/T+1m).
- The openbq-api `/apps.json` serves twelve BDOBB examples; the Live Grid example is served by live-grid's own `/apps.json` (its cards are none of the API's widgets).

**GHCR `10.0.0`**, built for amd64 and arm64 at `6cf51a9` unless noted:
- `openbq-local` `sha256:a15456837dff58b839fafbf21076b6674f736a5fbdd39f3391d21b3f3c85571f`, the `v3` stage, image revision `65e1d6a` (the seventh carry below; the sixth's was `c7425917…`, revision `a70dc82`)
- `openbq-mcp` `sha256:8e6a39b1c8165f367f9e0cfc423388133f5fd34929b3b4abebf0abb7fd75f610`, built FROM that `openbq-local`, image revision `65e1d6a` (the sixth's was `b8684de8…`)
- `openbq-funnel-gateway` `sha256:1acbb09e1fa9b1b9e8001bb9f8c41d761c7e4e45342f02494f0a93edde303f28`, image revision `148b7e3` (the fifth carry below; the fourth carry's was `7eb78a08…`, the third's `2e950e1c…`)
- `openbq-live-grid` `sha256:f83068001f9bee730f77bce3017d247eca11ad5766e87021e4289c217eb6982a`, image revision `f870ea8`
- `openbq-lake` `sha256:ac72245b3278f682910741fa811ef172be6bd2603e877708c8f30d6aceb757ff`
- `openbq-key-maint` `sha256:994fe7114e2350806e1663b6d1eba61175fba307e8976426fb74a5bde3032b56`
- `openbq-rss-ticker` `sha256:78fab9af79a0fd769154f95ebb7fd519b7cf44396f78ee4447e0104e6ef1de94`, image revision `c8aab8a` (rss-feedhandler v8.3.1)
- `openbq-table-service` `sha256:22423877f00a8c5c2de303bc0eb71e40d2f96aebc98816a50b28bd2d7021e3a4`, from BDOBB `dbcb257` per `table-service/source.lock.json` (the seventh carry below; the sixth's, from BDOBB `f77fbd8`, was `f4b6f192…`)

**Third carry (2026-10-18, late):** v9.0.0 `04ac6ab` brings Live TV (rss-ticker re-vendored from rss-feedhandler v8.3.1; the door still relays only `/news`) and v7.0.0 `b3a4d73`, so v8, v9 and v10 contain v7.0.0 again. CI's public-content scan now covers the checked-out ref's history (`--history HEAD`, 2f09eec), and `check-public.py` accepts `REPLACE_WITH_…` placeholders (fd1586c), so an unmerged branch's example token no longer fails it. rss-ticker 8.3.1 runs on production with its existing config, so Live TV answers "not configured" there; rss-ticker's own suite: 250 passed.

**Fourth carry (2026-10-19):** the door gzips its four root manifests (`/api` and `/ref` `widgets.json`, `apps.json`) for a caller that accepts gzip (`4ed861b`); data routes and other callers are unchanged, and `policy.mjs` is untouched, so BDOBB's 7f1a24e pairing and vendored hash stand. Why: off the tailnet, the Vercel preview showed the OpenBB API backend offline because openbq-api's 5.2 MB `widgets.json` took 18–60+ s through Funnel's public ingress (0.5 s on the tailnet), past the web layer's 12 s upstream timeout. Only the gateway image was rebuilt. On production, through the public ingress with the machine token: `/api/widgets.json` 512 KB on the wire in 0.7–0.8 s (5,212,796 bytes decoded), `/ref/widgets.json` 7.7 KB in 0.13 s; anonymous requests still 401. Gates: funnel-gateway 122 of 122, `check-public.py` PASS.

**Fifth carry (2026-10-19):** the one-symbol subscription DELETE accepts the caret on Node 22 (`148b7e3`). `requestUrl` compared the parsed pathname with the path after escaping `^` to `%5E`, which assumes the URL parser escapes it; Node 26 does, but the image's `node:22-alpine` keeps it raw, so on production `DELETE /grid/api/subscriptions/^GSPC` (and `%5EGSPC`) answered 421 and CI's Node 22 run failed tests 73 and 74. It now compares after unescaping `%5E`; the path holds no `%` by then, so that is the only escape it can be. `policy.mjs` is untouched. Only the gateway image was rebuilt. On production before the deploy, both caret forms answered 421; after it, both reach live-grid (404 for an unsubscribed symbol) and `%2e%2e` is still 421. `verify.mjs` PASS; anonymous requests through the door 401; `/api/widgets.json` with the machine token 200 gzip (511,622 bytes). `check-upstreams.mjs` stops at the API lock preflight (422, wants 401) on both the new and the previous image, since production runs the API with auth off. Gates: funnel-gateway 121 of 122 on Node 22 in `node:22-alpine` (the TLS test needs the `openssl` binary Alpine lacks) and 122 of 122 on Node 26; `check-public.py` PASS.

**Sixth carry (2026-10-19):** the table service builds BDOBB v10.0.0 `f77fbd8` (`3cc220e`): the web preview's saves no longer lost on a reload, a closed tab or an iPad sent to the background (BDOBB `65ed393a`…`bcf1176f`), and v9.0.0's long-press fix (PR #63, `0bf51435`). Only `openbq-table-service` was rebuilt; on production it is healthy, its `/app/source.json` names `f77fbd8` and tree `c25df737`, and the gateway reaches it on the private network. BDOBB pairs with `2e3b71e`; `policy.mjs` is unchanged since (sha256 `95e4c9ca…`). Gates: `tests` 73 passed, `check-public.py` PASS.

**Seventh carry (2026-10-19):** with the API's Basic auth on, `/widgets.json` and `/apps.json` stay open (`8d99ee2`, `65e1d6a`; user ruling, as `credentials.env.example` always said): the image's HEALTHCHECK curls `/widgets.json` without a credential, so a locked API could never report healthy, and BDOBB probes the catalogues the same way. The cache is built through openbb-api with the stack's own pair, never the caller's, and the caller's headers are restored after the build; data routes keep the lock. This reverses 8b57522/9baf63c (a cached catalogue answering 401); that test is replaced. The table service builds BDOBB v10.0.0 `dbcb257` (`c569159`): the web preview no longer replays a lapsed-session edit (`5e44ed6a`) and the Live Chart's intraday axis reads local hours (PR #64). Rebuilt: `openbq-local` (`--target v3`), `openbq-mcp` on it, `openbq-table-service`. Production's lock is the regression session's (`api-auth.env` for openbq-api, the pair only for live-grid); it repins these images. Gates: `tests` 73, `v3/tests` 68, `workspace/tests` OK, lanes 89 passed (1 skipped), `check-public.py` PASS; independent review, no Critical or Important findings.

`latest` was not moved.
