<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# v10: the live-grid and kdb+ port (ledger)

Episode 10. Branch `claude/openbq-docker-v10`, made from `claude/openbq-docker-v9`
69c907e. Local commits only. Nothing is pushed, tagged, built, run or deployed.

The donor is bdobb-dev/openbb-docker, read only (a blobless clone). Ported through
v10.1.7 (`d606169`), measured from v9.6.3 (`99864f2`, an ancestor of d606169; 583
commits, 222 files). The two repositories share no git history, so every carry is a
hand port, and each commit names the donor commits it ports. This line keeps its own
OpenBB Platform 5.0 (openbb-core 2.0.1, `requirements.lock`); nothing in the API
image changes.

Decisions marked **PROVISIONAL** are listed together at the end.

## Commits

| Commit | What |
|---|---|
| `c6936fd` | kdb-store/, kdb-ws/, kdb-license/.gitkeep, .gitignore |
| `645b49f` | live-grid/ (app, widgets.json, apps.json, macros, scripts, tests, Dockerfile) |
| `e24ed9c` | the `live` compose profile (kdb, live-grid), credentials.env.example, NOTICE, tests/test_live_profile.py |
| `7853cec` | funnel-gateway: the /grid family, v10.0.0 |
| `1c9f3c4` | this ledger, README |
| `a5e146b` | crash recovery always on (user ruling; see "Crash recovery and the S3 tier") |
| `724739e` | the S3 tier: RustFS, rustfs-init, eod-dump, openbb-deltalake, live-grid read-back |
| the ledger commit after it | the section below, README, kdb-ws/README |

## Ported paths

### live-grid, kdb-store, kdb-ws (content = the donor tree at d606169)

| Area | Donor commits (substantive, in v9.6.3..v10.1.7 unless marked) | Disposition |
|---|---|---|
| `kdb-store/` (15 files) | 446e8ca extraction; b6ce372 configurable bind; 93fcd88 tick reader (v10.1.0); b92dc97 fixed-width buckets (v10.1.4); headers a10ac7d/e520b60/baee69b | ADD, verbatim |
| `kdb-ws/` (7 files) | fba775a websocket publish; 3ece955 avwap buckets; d26effb tick log; f6857e1 + 201287e stats wmax/mphy (v10.1.5) | ADD, verbatim. `startup.q`/`persist.q` are what the kdb service runs; `live-chart.html` is copied into live-grid's image; `smoke.mjs`/`run-test.sh`/`gen.q` need a real q (Mac-pending) |
| `kdb-license/.gitkeep` | 59a9b96 | ADD (mount point only) |
| `live-grid/app/` | f15e08f base service; 0cea89c Basic auth; 8d852f0 /symbol_meta; e2789ee subscriptions; cd28309 unified chart; 938ee74 history by asset class; 93fcd88 /ticks and day levels (v10.1.0); 369074e /apps.json (v10.1.0); 7202f75 /health subscriptions reason (v10.1.4); b92dc97 series buckets (v10.1.4); the ta series (4fb851f, 4207888, 2f684bb, 10bfc04, f2d242a, 349aac4, 934bdf5, b26d198, 2c343b4) | ADD; one edit (`openbb_client.py`, below) |
| `live-grid/widgets.json` | f87018a column widths (v10.1.1) | ADD, verbatim |
| `live-grid/apps.json` | 7202f75 (v10.1.4, #72); 369074e serves it | ADD, verbatim (sha256 `26be230f…046d`, identical to the donor); replaced by BDOBB's Episode 10 example in the v10 sync (see "BDOBB examples sync") |
| `live-grid/macros/`, `scripts/`, `tests/`, `Dockerfile`, `pyproject.toml`, `README.md` | f75b599, ef0a3aa (v10.1.0), d89076c, 55b68b5, 0ceac3d, 7202f75 | ADD; edits below |

The per-file record (last substantive donor commit and whether the file was new,
changed or unchanged in the range) is the appendix.

### Edits to donor files

- `live-grid/app/openbb_client.py`: `OPENBB_HISTORY_NAMESPACE` (PROVISIONAL, P2). Set to
  `eodhd`, `fetch_series` calls `/api/v1/eodhd/<equity|crypto|currency>/price/historical`
  with `provider=eodhd` whatever provider the route was given. Unset is the donor's code
  path, byte for byte in behaviour; every donor test runs unset.
- `live-grid/scripts/smoke.py`: EODHD's public demo websocket key is read from
  `EODHD_DEMO_WS_KEY` instead of being committed (key hygiene, as at v9). With no key the
  script prints SKIP and exits 2.
- `live-grid/tests/test_main.py`, `tests/test_subscriptions.py`: the example tailnet name is
  built at run time (`EXAMPLE_TAILNET`) so `scripts/check-public.py` passes. Same values,
  no assertion changed.
- `live-grid/README.md`: an openbq-docker preface; the donor text is kept below it.
- New: `live-grid/tests/test_openbq_v10.py`, `live-grid/tests/fixtures/openbq_eodhd_history.json`
  (recorded OBBject shape, fictional values).

### funnel-gateway (a three-way merge: base donor v8.0.3, ours v9, theirs d606169)

| File | Donor commits | Notes |
|---|---|---|
| `policy.mjs` | e8c1239 grammars, `upstreamPath` /grid, `liveGridSubscription`, `socketTarget`; b9545f5 /grid/ticks; dc61be8 /grid/ta_chart and `/grid/ta_chart_ws` in `socketTarget` | Equal to the donor's d606169 file except the removed /ai block and naming. **Changed: BDOBB must re-vendor it.** sha256 `1e6aa6c684e48194098acc8db2cf990db8d8096b45fdb2a661a89a3590ca5083` (v9: `dfa61ddf…0bfd0`) |
| `server.mjs` | e8c1239 target/connectGrid; 7212a1d back-pressure bound, METERED_GRID, OPTIONAL_DOCS, getJson status, Origin on connectGrid; b9545f5 symbol_meta metered; d32966d per-symbol frame metering, FRAME_CAP; dc61be8 the push-only socket; d7ec9d1 + 04e6089 no free first frame or push | `liveGrid` off → 503 (P4); SOCKS/Rita stay removed |
| `config.mjs` | e8c1239 `gridOrigin` fixed in code | `http://live-grid:6903` (the compose service), `null` unless `"liveGrid": true` (P4) |
| `check-upstreams.mjs` | e8c1239 live-grid /health preflight | only when `gridOrigin` is set; the v8 lock probe kept |
| `verify.mjs` | e8c1239, b9545f5, dc61be8, 995e06a (ta_chart_ws by refusal only) | grid 101 or 503 by `liveGrid` |
| `gateway.test.mjs`, `policy.test.mjs` | the tests of all of the above (d32966d, d7ec9d1, 04e6089 included) | fixture sets `liveGrid: true`; one stub made lock-aware; new off-state tests |
| `README.md` | daf3b4a and the donor's "The grid" section, rewritten for this line | |
| `package.json`, `package-lock.json`, compose tag, `Dockerfile` comment | a094666 (the gateway's own version) | 10.0.0 (P7) |
| `settings.example.json` | — | `"liveGrid": false` |

Not taken from the donor's gateway: `DEPLOYMENT.md` (this line keeps its operator notes in
the README), `socks.test.mjs` and every /ai and SOCKS5 piece (removed at v8).

## The compose design

- `live` profile, new: `kdb` and `live-grid`. `docker compose --profile live up -d`.
- Default stack (no profile): `tailscale` and `openbq-api` only, definitions identical to
  v9 (parsed and compared against 69c907e: no default or `workspace` service changed; in
  the `web` profile only `funnel-gateway`'s image tag changed). New top-level volume
  `live-grid-data`, used only by live-grid.
- `kdb` (as first ported; a5e146b changes the command, `/data` and the script mounts, see
  "Crash recovery and the S3 tier"): `ghcr.io/artcashin/kdb-x:amd64`, `command: ["/data/startup.q"]`, `KX_PORT=5000`
  (all interfaces of its own container, i.e. the bridge), `QLIC=/opt/kx-license`,
  `./kdb-license:/opt/kx-license:ro`, `./kdb-data:/data`. No host port, no Serve entry (P3).
- `live-grid`: build context `.`, `live-grid/Dockerfile`, image `openbq-live-grid:10.0.0`,
  uvicorn on `0.0.0.0:6903`, `credentials.env` (optional) for `EODHD_API_KEY` and the
  `OPENBB_API_*` pair (it enforces that pair on its own routes when `OPENBB_API_AUTH=true`),
  `KDB_EMBEDDED=false`, `KDB_BIND_HOST=kdb`, `KDB_PORT=5000`, `OPENBB_URL=http://openbq-api:6900`,
  `OPENBB_HISTORY_NAMESPACE=eodhd`, `TA_PUSH_INTERVAL_MS=1000`, `TA_EODHD_MIN_REFETCH_S=60`,
  the licence read-only, the watchlist on `live-grid-data`. No host port, no Serve entry.
- `web` profile: unchanged in shape. The /grid routes live in the gateway; the gateway does
  not `depends_on` live-grid, so `--profile web` alone still starts and answers 503 on /grid.
- Licence and keys: `.gitignore` adds `kdb-license/*` (except `.gitkeep`), `*.lic`,
  `kdb-data/`, `live-grid-data/`; `credentials.env.example` adds `LIVE_GRID_PUBLIC_URL=`
  (empty). Proved by `tests/test_live_profile.py`.

## The /grid route list (for the BDOBB client)

All behind `Authorization: Bearer <GATEWAY_TOKEN>`, `Host` = `origin`, `Origin` (if sent) = `origin`.

| Route | Method | Parameters | Metered (daily `quoteDailyLimit`) |
|---|---|---|---|
| `/grid/widgets.json` | GET | none | no |
| `/grid/apps.json` | GET | none; an upstream 404 is relayed as a bare 404 | no |
| `/grid/live_grid` | GET | `symbol` (comma list) | 1 |
| `/grid/symbol_meta` | GET | `symbol` (comma list); upstream 404 relayed | 1 |
| `/grid/series` | GET | `symbol` (one), `interval`, `start`, `end`, `provider` (`kdb`/`eodhd`) | 1 |
| `/grid/chart` | GET | as `/grid/series`, plus `theme` (`light`/`dark`) | 1 |
| `/grid/ticks` | GET | `symbol` (one), `limit` (1–1000) | no |
| `/grid/ta_chart` | GET | `symbol`, `interval`, `source` (`local`/`eodhd`), `macro`, `indicators`, `anchor`, `start`, `end`, `theme`; no `provider` | 1 |
| `/grid/live_grid_ws` | GET + Upgrade | no query; frames `{"params":{"symbol":"A,B"}}`, each re-validated | 1 per symbol per frame, the first included |
| `/grid/ta_chart_ws` | GET + Upgrade | the `/grid/ta_chart` query is the subscription; no client frames | 1 per push, the first included |

`interval` ∈ 1s 5s 15s 30s 1m 5m 15m 30m 1h 4h 1d; on this line history is EODHD's, so only
1m, 5m, 1h and 1d return bars (P2). Each socket costs six per-minute units at upgrade; later
frames or pushes one more each; `FRAME_CAP` = 60 per socket; `maxSockets` applies. With
`liveGrid` off every one of these answers 503 after its route rules pass.

**How a browser authenticates the /grid socket.** It cannot send the Bearer token. BDOBB's
web layer (which has checked the user's session) signs a socket ticket and the browser opens
the socket directly on the door: `wss://<origin><target>?ticket=<ticket>` (or
`&ticket=` after the ta_chart query), with `Origin: <previewOrigin>` and no `Authorization`.
`target` is exactly what `policy.mjs` `socketTarget()` returns: `/grid/live_grid_ws`, or
`/grid/ta_chart_ws?<the query re-serialised by the /grid/ta_chart grammar>`. The ticket is
`<expiry>.<nonce>.<sig>`: 13-digit epoch ms at most 30 s ahead, 16 random bytes base64url,
and base64url HMAC-SHA256 over `"<expiry>.<nonce>.<target>"` with key
`HMAC-SHA256(GATEWAY_TOKEN, "bdobb socket ticket v1")` (`policy.mjs` `socketTicket`). It must
be the last parameter, spelled literally, used once. Tickets are off until `previewOrigin` is
set. The gateway then presents the stack's Basic pair to live-grid itself; the browser never
holds it.

## Excluded, and why

| Donor path or piece | Why |
|---|---|
| `openbb-kdb/` (the kdb read-through cache provider) | An openbb-api provider extension: it needs the standard routers (`openbb-equity`, `-crypto`, `-currency`) this line does not install, and installing it would change the default stack's API image. live-grid reads history from the EODHD namespace instead (P1, P2). |
| `kdb/` (bring-your-own q for openbb-api's embedded spawn) | Only openbb-api spawns q there; here kdb is its own service and live-grid never spawns (P1). |
| `kdb-x/` (the KDB-X image recipe) | The stack pulls `ghcr.io/artcashin/kdb-x:amd64`; this repo builds no kdb image (P1). |
| The donor's `127.0.0.1:5999` publish and Serve `:5999 -> kdb:5000` | q executes arbitrary code with no auth; nothing here needs the host or tailnet path (P3). |
| A Serve entry for live-grid `:6903` | Changing `ts-config/serve*.json` would change the default stack's sidecar; BDOBB reaches live-grid through `/grid` (P3). |
| tick-lab, live-grid-studies (`/grid/ta_registry`, `/grid/live_grid_studies`, study sockets) | Out of scope. Not on the donor's v10.1.7 line either; the sidecar does not need them. |
| deltalake, minio, security-master, mcp_charts/charts-mcp, stores-explorer, sip-backfill | Out of scope; live-grid imports none of them. (Superseded in part by the 2026-10-12 user rulings: openbb-deltalake and eod-dump are ported, MinIO is replaced by RustFS; see "Crash recovery and the S3 tier".) |
| key-maint, and d606169 (its log fix) | Out of scope; live-grid does not need it, so d606169 is not taken. |
| `api_app.py`, `api-auth.env.example`, `docker-entrypoint.sh`, `obb`, `obb-up`, `scripts/*` (scrub, widget_smoke, check-gateway-profile, patch_openbb_core_auth), `tests/test_api_app_auth.py` | The donor's own stack; this line has its own (see v9). |
| `funnel-gateway/DEPLOYMENT.md`, `socks.test.mjs` | See the gateway table. |
| The donor's demo websocket key in `credentials.env.example` and `scripts/smoke.py` | No key value is committed here. |
| `openbb-eodhd` changes in the range (afe372e, d0cb8d1, 34c38c6, 73dc8a3's floor) | v9 took openbb-eodhd at v9.6.6; unchanged here. |

## OpenBB Platform 5.0 fixes: taken or rejected

| Donor fix | Ruling | Proof |
|---|---|---|
| 73dc8a3 `openbb[routers]==5.0.0` | REJECTED | This line ships no standard routers (v9 PROVISIONAL 2). live-grid does not import openbb-core. |
| 73dc8a3 `scripts/patch_openbb_core_auth.py` | REJECTED (already have it) | Ruled at v9 with a failing/passing test pair; `provider-fixes/tests` 42 OK again here. |
| 73dc8a3 extension constraints `fastapi>=0.137.2`, `uvicorn>=0.48.0` | NOT NEEDED | Met by the lock (fastapi 0.142.2, uvicorn 0.54.0). live-grid's own image resolves its own (`fastapi>=0.110`; the venv here got 0.143.0). |
| 73dc8a3 CFTC patch removal, `openbb-kdb` core floor, government_us -> us_treasury | NOT APPLICABLE | Removed by the donor itself / openbb-kdb excluded / the example ids were already us_treasury at v9. |
| 2593c91 drop the providers 5.0 no longer ships | NOT APPLICABLE | key-maint and the donor's provider maps only. |
| 34c38c6 eodhd parity CI needs the standard routes | REJECTED | This line has no standard routes; v9/eodhd/tests checks the routers-less contract instead. |
| d606169 key-maint log fix | NOT TAKEN | key-maint is not ported. The same hazard exists in live-grid (`app/ta/sources.py` puts `api_token` in an httpx query string), but live-grid configures no logging handler (no `basicConfig`), so httpx's INFO request lines are never emitted and uvicorn configures only its own loggers. Recorded, not changed; checked on the Mac (below). |

No 5.0 fix was needed for live-grid, kdb-store or the gateway: none of them imports
openbb-core.

## PROVISIONAL decisions

1. **P1** The kdb tier taken is what live-grid uses directly: kdb-store and kdb-ws (with
   kdb-license/.gitkeep). openbb-kdb, kdb/ and kdb-x/ are excluded.
2. **P2** live-grid reads history from openbq-api's EODHD namespace
   (`OPENBB_HISTORY_NAMESPACE=eodhd`, provider pinned to `eodhd`). There is no kdb history
   cache, so each `/series`, `/chart`, `/ta_chart` call and each `/ta_chart_ws` push is an
   openbq-api → EODHD history call (the gateway meters each one; `TA_PUSH_INTERVAL_MS` stays
   at the donor's 1000). Intervals other than 1m, 5m, 1h, 1d fail upstream (live-grid answers
   its own 502 envelope). The `provider` parameter is accepted and ignored.
3. **P3** kdb and live-grid publish nothing: no host port (the donor's `127.0.0.1:5999` is
   dropped) and no Serve entry for either. BDOBB reaches live-grid only through `/grid`.
4. **P4** The gateway's `/grid` family is switched by a new settings key, `"liveGrid": true`;
   off by default, then 503. `gridOrigin` is the compose service name `live-grid`, fixed in
   code. The gateway does not `depends_on` live-grid.
5. **P5** live-grid loads `credentials.env` (this line has no `api-auth.env`), so it sees the
   provider keys as well as EODHD's and the Basic pair, as openbq-api does.
6. **P6** live-grid's watchlist is the named volume `live-grid-data` (the donor bind-mounts
   `./live-grid-data`, which stays git-ignored); kdb's `/data` stays the donor's bind
   `./kdb-data`, because the operator puts `startup.q` there. **Superseded for kdb by
   a5e146b** (user ruling, crash recovery): kdb's `/data` is now the named volume
   `kdb-data` and the q scripts are mounted from the repository; see C1 below.
7. **P7** The gateway is versioned 10.0.0 (package, lock, compose tag, README).

## Test receipts (cloud, 2026-10-12)

| Suite | Environment | Result |
|---|---|---|
| `live-grid` (donor suite + `test_openbq_v10.py`) | venv `lg312` in the scratchpad: Python 3.12.3, `kdb-store` installed, PyKX 4.1.0 (unlicensed), fastapi 0.143.0, pandas 3.0.6, polars 2.0.0; no eodhd SDK | 414 passed, 14 deselected (the donor's `network` marker) |
| `live-grid -m network` | same, `EODHD_API_KEY` absent | 2 passed, 12 skipped (no key; no call made) |
| `live-grid/tests/test_openbq_v10.py` | same | 11 passed, including the no-kdb tests against the REAL kdb_store session on a closed port (log: "kdb+ unavailable, falling back to upstream") |
| `kdb-store` | same | 127 passed (fakes; no q) |
| `funnel-gateway` `npm test` | node 22.22.0 | 75 passed (v9: 47) |
| `tests/` | lock + overlay (`img312`) | 14 passed (5 subtests) |
| `v3/tests` | `img312` | 68 passed |
| `lanes/tests` | `img312` | 22 passed |
| `workspace/tests` | `img312` | 12 passed |
| `examples/episode3` `test_server`, `test_assembly` | `img312` | 6 passed |
| `provider-fixes/tests` | `pf312` (the v9 lock with the overlay already applied) | 42 OK |
| `v9/eodhd/tests` | `img312` (lock + overlay + openbb-eodhd) | 9 passed |
| `scripts/check-public.py` | — | PASS |
| `scripts/verify-app-layouts.py live-grid/apps.json` | — | passed, no overlaps |
| Intermediate commits c6936fd, 645b49f, e24ed9c | worktrees | gateway 47/47 and `tests/` green at each |

No assertion was weakened, skipped or deleted. EODHD calls: 0.

## NOT_RUN and Mac-pending

- `docker compose --profile live build` and `up`: the live-grid image (plotly.js download,
  the eodhd SDK from its pinned GitHub archive, `pip install` of kdb-store), the kdb-x pull,
  q running `startup.q` with a real licence, live-grid recording ticks into it and
  `/health`'s `ticks.endpoint` reading `kdb:5000`.
- `kdb-ws/run-test.sh` and `smoke.mjs` (docker + licence), `kdb-store/scripts/tick_check.py`.
- live-grid against a real EODHD key: the websocket feed, `/live_grid`, `/symbol_meta`,
  `scripts/smoke.py`, `smoke_live.py`, `smoke_ta.py`, the 12 `network` parity tests.
- live-grid → openbq-api `/api/v1/eodhd/.../price/historical` on the running stack, with the
  Basic pair, for an equity, a crypto and a forex symbol.
- The gateway in the running `web` + `live` profiles: `check-upstreams.mjs` (including its
  pre-existing v8 API probe of `/api/v1/equity/price/quote` on this routers-less build) and
  `verify.mjs` on the bridge and through Funnel, with `"liveGrid": true` and false.
- `docker compose logs live-grid` after a `source=eodhd` tick chart: no `api_token` value appears.
- BDOBB's web preview opening `/grid/live_grid_ws` and `/grid/ta_chart_ws` with tickets.

## Crash recovery and the S3 tier (user rulings, 2026-10-12)

### The rulings

These are **user rulings**, given in this session on 2026-10-12. They are not provisional.

1. **Crash recovery.** v10 needs crash recovery: the standard tick-spooling script writes
   ticks to the filesystem, and they are replayed when a service needs a restart.
2. **The S3 file system.** v10 also needs the S3 file system, to store the ticks for the
   kdb cache. The donor's S3 tier first appears at v11.0.0 (Episode 11). **These are
   Episode 11 donor items, moved into v10 by user ruling.**
3. **RustFS instead of MinIO.** The S3 store is RustFS (`rustfs/rustfs`, Apache-2.0), not
   MinIO. The user's reason is MinIO's licence change: they do not want people building on
   something that will go stale. RustFS is meant to be a drop-in S3-compatible
   replacement. Neither `mc` (the MinIO client, AGPL) nor any MinIO binary or image may
   remain.
4. **Keep Delta Lake.** The store format stays Delta Lake (delta-rs); no switch to DuckLake.

Everything else stands as ruled for Episode 10: the opt-in `live` profile, the default
stack unchanged, OpenBB Platform 5.0 kept, local commits only, no docker run here.

### Crash recovery (a5e146b)

| Path | Donor | Disposition |
|---|---|---|
| `kdb-ws/persist.q` | d26effb (tagged v10.1.0 line; unchanged through v10.1.7 d606169 and the donor's main) | Already ported at c6936fd; now always loaded |
| `kdb-ws/startup.q` | f6857e1 (v10.1.5) | EDIT: the last line loads `KDB_PERSIST_Q`, default the donor's `/data/persist.q` |
| `docker-compose.yml` `kdb` | the donor's `command: ["/data/startup.q"]` on the kdb-x entrypoint (`exec q "$@" -p $KX_PORT`, kdb-x/entrypoint.sh at d606169) | EDIT: see below |
| `kdb-ws/tests/tickplant_sim.py`, `kdb-ws/tests/test_persist.py`, `kdb-store/tests/test_crash_recovery.py`, `live-grid/tests/test_crash_recovery.py` | none | NEW |

The `kdb` service now mounts `./kdb-ws/startup.q` and `./kdb-ws/persist.q` read-only at
`/opt/kdb-ws/`, runs `["/opt/kdb-ws/startup.q"]` with `KDB_PERSIST_Q=/opt/kdb-ws/persist.q`,
and keeps `/data` on the named volume `kdb-data` (persist.q's `/data/logs/tlog_<date>`),
which survives `docker compose down`/`up` and container recreation (`down -v` deletes it).
`restart: unless-stopped` (both kdb and live-grid) and `stop_grace_period: 30s` so q's
`.z.exit` closes the log handle. The operator copies nothing by hand any more.

**Reconnection.** kdb-store's `session.py` and `store.py` and live-grid's `recorder.py` are
byte-identical to the donor's latest (main and v11.5.4; last substantive commits b6ce372,
93fcd88, 2fc9b6b). The behaviour the tests prove: a dead connection fails its `1+1` liveness
check; the next call walks the chain again to `kdb:5000`; the expiring 60 s latch
(25ba5f7's fix, in b6ce372's session.py) suppresses retries during an outage and picks up a
q that came back; the schema statement is re-issued on the new connection; a flush during
the outage is counted in `dropped` and does not kill the feed. Nothing to take. Not taken:
b569994 (forex feed liveness) and 0cf96ab (drain interval), which are feed tuning, not
restart recovery.

What a restart loses, by design: ticks EODHD sends while live-grid is down (no feed), and a
flush that fails while kdb is down (bounded buffer, counted in `/health` `ticks.dropped`).

### The S3 tier (724739e)

| Path | Donor commits (tag) | Disposition |
|---|---|---|
| `openbb-deltalake/` (22 files) | 2b02ed7, 0e1b465, c5a06ae, 6dd737b, bf07da0, 9ad866f, 7b40ab1 (v11.0.0 line, 2026-09-01); 3b10505, b6653a7 (2026-09-03/04); d999ebe, ed38326 (v11.0.1); 23f076a (docs); f69689e (openbb-core 2.0.1 floor, v11.0.6); headers 78c7af9/2e5af70/b7045aa | ADD, content = v11.0.6 (`afda165`). Edits: README preface; tests build the example tailnet suffix at run time and use `EXAMPLE_*` secrets so `check-public.py` passes (same assertions). Installed only in the openbq-lake image |
| `scripts/eod_dump.py` | 4b84311, 7fc889b, a061853 (v11.0.0); 714d43c (v11.0.1) | ADD, from v11.0.6. Edits below |
| `docker-compose.yml` `eod-dump` | ec5e738 (v11.0.0), 714d43c | ADD, rewritten for this line |
| `docker-compose.yml` `rustfs`, `rustfs-init`, volume `rustfs-data` | shape from a7d5b3e/ec5e738 (`minio`, `minio-init`, `minio-data`, v11.0.0) | REPLACED by RustFS (ruling 3) |
| `rustfs.env.example` | minio.env.example (a7d5b3e, b1374ac, d999ebe; v11.0.0..v11.0.6) | REPLACED: RustFS names, empty secrets, the `DELTA_S3_*` contract kept |
| `eod.env.example` | 714d43c (v11.0.1) | ADD, hot mirror off |
| `Dockerfile.lake` (`openbq-lake:10.0.0`) | the donor's `openbb-local` image as eod-dump's runtime (ec5e738) | NEW: the counterpart, separate from openbq-api |
| `scripts/s3_init.py` | replaces `minio-init`'s `mc mb --ignore-existing` (a7d5b3e) | NEW, S3 API via pyarrow |
| `live-grid/app/lake.py`, `live-grid/app/main.py` (`build_series(..., lake=)`), `live-grid/pyproject.toml` (+deltalake, pyarrow) | none at v11 (the donor's v11 live-grid never reads Delta; its later tick vault, d07898b, is Episode 12+) | NEW, the read-back (C4) |
| `scripts/tests/test_lake_scripts.py`, `live-grid/tests/test_lake_readback.py`, `tests/test_lake_profile.py` | none | NEW |
| `.gitignore`, `NOTICE`, `README.md`, `kdb-ws/README.md` | none | EDIT |

Edits to `scripts/eod_dump.py`: the NAS-side HTTP read (`_read_day_http`, `KDB_HTTP_URL`,
06ee951) is removed, so the flush reads kdb over IPC on the bridge only; `main()` exits 2
without all of `DELTA_S3_*` (openbb-deltalake's `layer_target` would otherwise write into a
directory inside the container, and does not read `DELTA_URI`); `EOD_HOT_SESSIONS` defaults
to 0 (one store here; the donor's 10 would write a second copy into the same bucket).

The `DELTA_S3_*` contract is the donor's (openbb-deltalake `utils.s3_options_from_env`):
`DELTA_S3_ENDPOINT=rustfs`, `DELTA_S3_PORT=9000`, `DELTA_S3_SECURE=false` (plain HTTP on the
bridge, so `aws_allow_http=true`), `aws_virtual_hosted_style_request=false` (path-style:
`rustfs` is a service name, never `<bucket>.<host>`) and `aws_conditional_put=etag`, all kept.

Not taken from the donor's S3 tier:

| Donor path or piece | Why |
|---|---|
| `minio/` (Dockerfile, entrypoint.sh, cert-sync.sh, tests/) | EXCLUDE, superseded by the RustFS ruling |
| 785fef8 (v11.0.5), 12cfc20 + d75a48d (v11.3.4), a5e6f4a (v11.2.6): MinIO from release binaries, not withdrawn images | EXCLUDE, superseded by the RustFS ruling |
| cert-sync and the `minio-ts-state` volume | MinIO joined the tailnet with its own certificate. RustFS here is on the bridge only, no tailnet node, so nothing needs a certificate (decision under the ruling's "keep cert-sync only if needed") |
| `minio-hdd`, `minio-hdd-init`, the hot/cold tier variables (`DELTA_S3_HOT_*`/`COLD_*`, `LAKE_*_URI`) | NAS/HDD deployment; the code that reads them is kept (it falls back to the single store) but nothing configures them |
| eod-dump's `KDB_HTTP_URL` path and kdb's Serve `:5999` | the NAS-only production flush; nothing publishes kdb here (P3) |
| `openbb-deltalake` in openbq-api (`provider="deltalake"`) | would change the default stack's API image (as openbb-kdb, P1) |
| tick-lab, mcp_stores, stores-explorer, `tests/integration/*` (MinIO concurrency, provider parity) | out of scope; need the donor's API image or a live store |
| `quay.io/minio/minio`, `quay.io/minio/mc`, any MinIO binary | ruling 3. `tests/test_lake_profile.py` fails on any `minio` service, image or volume, or `mc`, in compose |

### RustFS

- Image `rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
  the index digest (linux/amd64 and linux/arm64) read from Docker Hub's registry API on
  2026-10-12 (metadata only; nothing pulled or run). 1.0.1 was published 2026-10-03, the
  newest non-preview release (1.0.0 GA was 2026-09-16), and is after 2026-02-02, when
  RustFS issue **#1458** (conditional requests failed on unquoted ETags in put_object,
  copy_object and delete_object) was closed as fixed via s3s 0.13.0-alpha.2; that fix
  still awaits the reporter's confirmation. RustFS is reported to enforce
  If-None-Match/If-Match on PutObject since 1.0.0-alpha.47 (PR #409, cited second-hand in
  rustfs/cli #385). Conditional GET (#791) does not matter for Delta commits.
- Settings from the 1.0.1 Dockerfile, docker-compose.yml, entrypoint.sh and README (fetched
  from raw.githubusercontent.com at the 1.0.1 tag): `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY`
  (default `rustfsadmin`, which the entrypoint only warns about, so our compose wrapper
  refuses it), `RUSTFS_VOLUMES=/data`, `RUSTFS_ADDRESS=0.0.0.0:9000`,
  `RUSTFS_CONSOLE_ENABLE=false`, health `curl -fsS http://127.0.0.1:9000/health`, runs as
  uid 10001 (a fresh named volume takes the image's `/data` ownership).
- **Maturity.** 1.0 GA is four weeks old; the 1.0.1 line shipped 17 previews in a fortnight.
  It is young next to MinIO, and S3 compatibility is its own claim. What this stack relies
  on: path-style addressing, CreateBucket/HeadBucket, Get/Put/List/Delete, ranged GET
  (parquet), and **put-if-absent** (`If-None-Match: *`) on `_delta_log/*.json`, which is how
  delta-rs makes a commit atomic with `aws_conditional_put=etag` and no lock service. eod-dump
  is the only writer, once a day, so a conditional-put failure has no concurrent writer to
  race; live-grid only reads.

### Decisions (PROVISIONAL unless marked)

- **C1** (decision under ruling 1) kdb's `/data` is the named volume `kdb-data`, not the
  `./kdb-data` bind (P6 superseded); the scripts are read-only mounts plus `KDB_PERSIST_Q`
  (a one-line, defaulted edit to startup.q), not files copied into the volume.
- **C2** PROVISIONAL: RustFS conditional put. moto enforces put-if-absent (412) in the tests;
  RustFS's support is from its issue tracker, not verified. Until the Mac check below passes.
- **C3** PROVISIONAL: eod-dump and rustfs-init run in their own image, `openbq-lake:10.0.0`
  (Dockerfile.lake: python:3.12-slim at the same digest as Dockerfile, `--constraint
  requirements.lock`, openbb-core 2.0.1, deltalake 1.6.6, pykx 4.1.0, openbb-deltalake), not
  in openbq-api's image as the donor's eod-dump does, so the default stack is unchanged.
- **C4** PROVISIONAL: the read-back. The donor's v11 has no live-grid reader for flushed
  ticks (its eod-dump comment says the chart's seam reads the hot mirror, but no v11 code
  does). `live-grid/app/lake.py` is this line's own: for an intraday interval that tiles a
  UTC day (1m, 5m, 15m, 1h, 90m; not 7m, not 1d), each whole past UTC day in the request
  (at most `LIVE_GRID_LAKE_MAX_DAYS`, 10) that `ticks_live/<SYM>_<YYYY_MM_DD>` holds is
  aggregated like kdb's `xbar` and owns its span from its first fully covered bar to the end
  of the bar holding its last tick; kdb's ticks own only what follows the last such day;
  history fills the rest. Any store error degrades to the kdb path. `1d` and wider stay on
  history (a flushed day may be partial). Off unless `LIVE_GRID_LAKE_READBACK=true` and all
  of `DELTA_S3_*` are set (no local fallback directory). When on, `/series` and `/grid/series`
  `cache` gain `rows_from_lake` and `lake_days`; without it the response is unchanged.
- **C5** PROVISIONAL: every env file of the tier is `required: false`, and the tier fails
  closed at run time instead: rustfs exits on an empty or `rustfsadmin` pair, rustfs-init
  exits 2 without `DELTA_S3_*`, eod-dump never starts without a successful init, eod-dump
  exits 2 without the store. So a `--profile live` without `rustfs.env` still runs kdb and
  live-grid.
- **C6** PROVISIONAL: live-grid loads `rustfs.env` for the read-back, so it holds the store's
  root pair (as the donor's readers hold MinIO's root pair, b1374ac). A read-only scoped key
  would be better posture; RustFS IAM is not set up here.
- **C7** PROVISIONAL: `EOD_HOT_SESSIONS` defaults to 0 and the hot/cold tiers are unconfigured
  (one store).
- **C8** Finding: `DeltaTable.is_deltatable` never returned against an S3 endpoint in this
  environment (deltalake 1.6.6 and 1.1.4, moto; no request reached the server), while
  opening a table and catching `TableNotFoundError` returns at once. `lake.py` opens and
  catches. openbb-deltalake's `store.has()`/`read()` still call `is_deltatable`; eod-dump does
  not use them (it writes, lists with pyarrow and deletes), and they are tested on a local
  store. Check on the Mac against RustFS (below).

### Test receipts (cloud, 2026-10-12)

| Suite | Environment | Result |
|---|---|---|
| `kdb-ws/tests` (persist.q pins + the tick-plant simulation) | `lg312` | 9 passed |
| `kdb-store` (incl. `test_crash_recovery.py`, 3) | `lg312` | 130 passed (was 127) |
| `live-grid` (incl. `test_crash_recovery.py` 3, `test_lake_readback.py` 13) | `lg312` + deltalake 1.6.6, pyarrow 25.0.1, moto 5.2.4 | 430 passed, 14 deselected (was 414) |
| `openbb-deltalake` (the donor's suite) | `lake312`: Python 3.12.3, openbb-core 2.0.1 and shared pins from requirements.lock, deltalake 1.6.6, pykx 4.1.0, moto 5.2.4, kdb-store | 95 passed |
| `scripts/tests` (eod_dump, s3_init, against moto and a local store) | `lake312` | 13 passed |
| `tests/` (incl. `test_lake_profile.py` 10, new crash-recovery compose checks 3) | `img312` | 27 passed (5 subtests) (was 14) |
| `funnel-gateway` `npm test` | node 22.22.0 | 75 passed |
| `v3/tests`, `lanes/tests`, `workspace/tests` | `img312` | 68, 22, 12 passed |
| `examples/episode3` `test_server`, `test_assembly` | `img312` | 6 passed |
| `provider-fixes/tests` | `pf312` | 42 OK |
| `v9/eodhd/tests` | `img312` | 9 passed |
| `scripts/check-public.py` | — | PASS |
| `scripts/verify-app-layouts.py live-grid/apps.json` | — | passed |

One existing assertion changed with the design, not weakened: `tests/test_live_profile.py`
now expects live-grid's `env_file` to be exactly `credentials.env` and `rustfs.env` (both
optional), and kdb's command `/opt/kdb-ws/startup.q` (checked in the new crash-recovery
test). No test was skipped or deleted. EODHD calls: 0. Nothing was pulled, built or run.

### Mac-pending (crash recovery and the S3 tier)

Needs a KX licence in `kdb-license/`, `rustfs.env` filled, and the stack built:
`docker compose --profile live build && docker compose --profile live up -d`.

**1. kdb killed mid-session.**
1. With live-grid recording (watchlist has symbols, market open or a crypto symbol), note
   the count: `docker compose exec live-grid python -c "from kdb_store.config import resolve_config; from kdb_store.session import KdbSession; from kdb_store.store import KdbStore; s=KdbStore(KdbSession(resolve_config())); print(s._call(lambda c: c('count trades').py()))"`
   and `ls` the log: `docker compose exec kdb ls -l /data/logs`.
2. `docker compose kill -s SIGKILL kdb`, wait 10 s, `docker compose start kdb`
   (and once with `docker compose up -d --force-recreate kdb`, which recreates the container).
3. `docker compose logs kdb` shows `tlog: replaying tlog_<date>` and `tick log active`.
4. Re-run the count: it equals the count before the kill plus whatever arrived after
   live-grid reconnected (within 60 s, the retry latch), never less than before the kill.
   `/health` `ticks.endpoint` reads `loopback` again; `ticks.dropped` counts only the outage.
5. `/series?symbol=<sym>&interval=1m&start=<today>&end=<today>` has `cache.rows_from_ticks`
   > 0 and the same `seam` as before the kill.

**2. live-grid killed mid-session.**
1. Note `/ticks?symbol=<sym>&limit=1000` and the kdb count.
2. `docker compose kill -s SIGKILL live-grid`, then `docker compose up -d live-grid`
   (and once `--force-recreate`).
3. `/health` answers, the watchlist is back (`live-grid-data`), `/ticks` returns the same
   rows plus new ones, `/series` 1m has `rows_from_ticks` > 0. kdb's count did not drop.

**3. Both.** `docker compose --profile live restart`; repeat 1.4 and 2.3.

**4. RustFS and the flush.**
1. `docker compose ps`: rustfs healthy, rustfs-init exited 0, eod-dump running. With
   `rustfs.env` absent or holding `rustfsadmin`, rustfs exits 1 with the message.
2. Flush a day by hand: `docker compose exec eod-dump python /opt/eod_dump.py --date <yesterday>`;
   re-run it (the version goes 0 then 1, row count unchanged).
3. Read-back: `/series?symbol=<sym>&interval=1m&start=<3 days ago>&end=<today>` reports
   `cache.lake_days` including yesterday and `rows_from_lake` > 0; stop rustfs and repeat:
   the chart still answers (kdb + history), `rows_from_lake` 0.
4. **Conditional put (C2).** Against the real RustFS container, from the openbq-lake image on
   the bridge, run two concurrent delta-rs commits to the same table (two processes each
   opening the table at the same version and committing). One must fail with a commit
   conflict, HTTP 412 on `_delta_log/<n>.json`, not silently overwrite. Also a raw
   `PutObject` with `If-None-Match: *` on an existing key must answer 412. Until this passes,
   C2 stays PROVISIONAL.
5. **C8.** `DeltaTable.is_deltatable("s3://openbq/ticks_live/<key>", storage_options=...)`
   against RustFS returns promptly (or record that it hangs there too).
6. `docker compose logs live-grid eod-dump` show no `DELTA_S3_SECRET`/`RUSTFS_SECRET_KEY` value.

## BDOBB examples sync (v10)

`EPISODE=10 OPENBB_DOCKER_DIR=<scratch> node scripts/apps-sync.mjs` on BDOBB
`claude/clean-v10` 3e92d06 (12 apps: 11 to `workspace_apps.json`, 1 to
`live-grid/apps.json`), carried by the v8/v9 method (41bc742, 69c907e):

- `examples/bdobb/apps.json`: the 11 filtered to the examples whose cards are BDOBB
  built-ins or widgets openbq-api serves (the v9 filter, against the same served
  widget set): 9 kept, Demo providers and Video Library dropped as before. The result
  is **byte-identical** to the file at 69c907e, so it is unchanged; only its README
  names `EPISODE=10` and where the live-grid example goes.
- `live-grid/apps.json`: the v10 example maps to the `live` profile. live-grid's
  Dockerfile copies this file into its image, `GET /apps.json` serves it verbatim
  (`app/main.py`), and the gateway relays it as `/grid/apps.json`; openbq-api's
  catalogue and the lanes hook never see it. It is BDOBB's
  `docs/examples/v10.0.0-live-grid.apps.json` verbatim (sha256 `0c87828d…a39b`),
  replacing the donor's copy: *Example Dashboard - Version 10.0.0 - Live Grid*,
  the same five cards (`live_grid`, `subscriptions`, `kdb_ticks`, `live_chart`,
  `kdb_cache_chart`), the same saved params and layout, plus BDOBB's description
  (minimum BDOBB 10.0.0), `chartView` defaults and its `extensions.bdobb` tab order.
  Card ids checked against `live-grid/widgets.json` here: all five are declared;
  `subscriptions` is published only with `LIVE_GRID_PUBLIC_URL` set (empty in
  `credentials.env.example`, and P3 publishes no live-grid address), which BDOBB's
  Example Dashboards page now says.

Assertions changed with the file (none weakened; the selected app is the same one,
named as BDOBB names it):

- REVIEW `live-grid/tests/test_main.py` `test_the_v10_dashboard_shows_every_episode_10_widget`
  (donor): selected the app by `"V10" in name`; now by the exact name
  `Example Dashboard - Version 10.0.0 - Live Grid`. The five-widget assertion is unchanged.
- REVIEW `live-grid/tests/test_openbq_v10.py` `test_without_kdb_widgets_and_apps_are_served`:
  the served app list `== ["Example Dashboard - V10.0.0"]` becomes
  `== ["Example Dashboard - Version 10.0.0 - Live Grid"]` (still exactly one app, exact name).

Receipts (cloud, 2026-10-12): `tests/` 27 passed (5 subtests), `v3/tests` 68,
`lanes/tests` 22, `workspace/tests` 12 (`img312`); `live-grid` 430 passed, 14
deselected (`lg312`, `-m "not network"`); `scripts/check-public.py` PASS;
`scripts/verify-app-layouts.py` passed for `live-grid/apps.json` and
`examples/bdobb/apps.json`. EODHD calls: 0.

BDOBB re-vendored this branch's `funnel-gateway/policy.mjs` at ebd1622 (sha256
`1e6aa6c6…a5083`) as v10.0.0 (BDOBB c6d53f6); its `openbbDocker` pin names ebd1622.

## Appendix: per-file record (live-grid, kdb-store, kdb-ws, kdb-license)

Last substantive donor commit (licence-header-only commits a10ac7d, e520b60, baee69b and
c4aee25 skipped), the first v10 tag containing it (or "in v9.6.3"), and the file's status
in v9.6.3..v10.1.7. Content is the donor's d606169 file except where "Edits" above says so.

| Path | Last substantive commit | Status in range |
|---|---|---|
| `kdb-license/.gitkeep` | 59a9b96 (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/README.md` | 446e8ca (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/__init__.py` | 446e8ca (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/aggregate.py` | b92dc97 (v10.1.4) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/config.py` | b6ce372 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/ranges.py` | 446e8ca (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/session.py` | b6ce372 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/kdb_store/store.py` | 93fcd88 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/pyproject.toml` | 0ceac3d (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/scripts/tick_check.py` | 93fcd88 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/__init__.py` | 446e8ca (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/test_aggregate.py` | b92dc97 (v10.1.4) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/test_config.py` | b6ce372 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/test_ranges.py` | 446e8ca (v10.0.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/test_session.py` | b6ce372 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-store/tests/test_store.py` | 93fcd88 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/README.md` | 201287e (v10.1.5) | new in v9.6.3..v10.1.7 |
| `kdb-ws/gen.q` | fba775a (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/live-chart.html` | 3ece955 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/persist.q` | d26effb (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/run-test.sh` | fba775a (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/smoke.mjs` | 3ece955 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `kdb-ws/startup.q` | f6857e1 (v10.1.5) | new in v9.6.3..v10.1.7 |
| `live-grid/Dockerfile` | 369074e (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/README.md` | 7202f75 (v10.1.4) | changed v9.6.3..v10.1.7 |
| `live-grid/app/__init__.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/app/auth.py` | 0cea89c (v10.1.0) | unchanged since v9.6.3 |
| `live-grid/app/classify.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/app/feeds.py` | adc1d2a (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/app/figure.py` | cd28309 (v10.0.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/leases.py` | e2789ee (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/main.py` | 7202f75 (v10.1.4) | changed v9.6.3..v10.1.7 |
| `live-grid/app/openbb_client.py` | 938ee74 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/quotes.py` | 93fcd88 (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/app/recorder.py` | 2fc9b6b (v10.0.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/series.py` | b92dc97 (v10.1.4) | new in v9.6.3..v10.1.7 |
| `live-grid/app/static/demo.html` | 8d852f0 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/static/subscriptions.html` | e2789ee (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/symbol_meta.py` | 8d852f0 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/__init__.py` | f75b599 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/compute.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/exprs.py` | 4fb851f (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/figure.py` | 2c343b4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/iterative.py` | 4207888 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/macros.py` | b26d198 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/panes.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/payload.py` | 10bfc04 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/registry.py` | f2d242a (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/ta/sources.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/app/watchlist.py` | e2789ee (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/apps.json` | 7202f75 (v10.1.4) | new in v9.6.3..v10.1.7 |
| `live-grid/macros/classic-momentum.yml` | 2f684bb (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/macros/volatility-squeeze.yml` | 2f684bb (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/pyproject.toml` | ef0a3aa (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/scripts/smoke.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/scripts/smoke_live.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/scripts/smoke_ta.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/__init__.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/tests/conftest.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/tests/fixtures/make_fixture.py` | f75b599 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/fixtures/ohlcv.csv` | f75b599 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/ta_helpers.py` | f2d242a (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_auth.py` | 0cea89c (v10.1.0) | unchanged since v9.6.3 |
| `live-grid/tests/test_auth_routes.py` | 0cea89c (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/tests/test_chart_routes.py` | 93fcd88 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_classify.py` | f15e08f (v10.0.0) | unchanged since v9.6.3 |
| `live-grid/tests/test_feeds.py` | adc1d2a (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/tests/test_figure.py` | cd28309 (v10.0.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_leases.py` | aa5af88 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_main.py` | 7202f75 (v10.1.4) | changed v9.6.3..v10.1.7 |
| `live-grid/tests/test_quotes.py` | 93fcd88 (v10.1.0) | changed v9.6.3..v10.1.7 |
| `live-grid/tests/test_recorder.py` | 2fc9b6b (v10.0.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_series.py` | b92dc97 (v10.1.4) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_subscriptions.py` | e2789ee (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_symbol_meta.py` | 8d852f0 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_compute.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_conventions.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_exprs.py` | 55b68b5 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_figure.py` | 2c343b4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_iterative.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_live.py` | 934bdf5 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_macros.py` | b26d198 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_panes.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_parity.py` | d89076c (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_payload.py` | 10bfc04 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_registry.py` | f2d242a (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_routes.py` | 10bfc04 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_ta_sources.py` | 349aac4 (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/tests/test_watchlist.py` | e2789ee (v10.1.0) | new in v9.6.3..v10.1.7 |
| `live-grid/widgets.json` | f87018a (v10.1.1) | changed v9.6.3..v10.1.7 |
