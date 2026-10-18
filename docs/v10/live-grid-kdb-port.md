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
| `2718052`..`9b98f50` + docs | tick spool and fast reconnect (user ruling; see "Tick spool and fast reconnect") |

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
| `policy.mjs` | e8c1239 grammars, `upstreamPath` /grid, `liveGridSubscription`, `socketTarget`; b9545f5 /grid/ticks; dc61be8 /grid/ta_chart and `/grid/ta_chart_ws` in `socketTarget` | Equal to the donor's d606169 file except the removed /ai block and naming. **Changed: BDOBB must re-vendor it.** sha256 `ceadbbe541289bc2517946681c39cb0305475acf213fe51cdccad96f35abe71a` since the 2026-10-16 review fixes (D24: comment-only, forward references removed; earlier `1e6aa6c6…a5083`, v9: `dfa61ddf…0bfd0`) |
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

All behind `Authorization: Bearer <GATEWAY_TOKEN>`, `Host` = `origin`, `Origin` (if sent) = `origin`
or, since V10-P1 (2026-10-15), one of the packaged desktop origins `tauri://localhost` and
`http://tauri.localhost`.

| Route | Method | Parameters |
|---|---|---|
| `/grid/widgets.json` | GET | none |
| `/grid/apps.json` | GET | none; an upstream 404 is relayed as a bare 404 |
| `/grid/live_grid` | GET | `symbol` (comma list) |
| `/grid/symbol_meta` | GET | `symbol` (comma list); upstream 404 relayed |
| `/grid/series` | GET | `symbol` (one), `interval`, `start`, `end`, `provider` (`kdb`/`eodhd`) |
| `/grid/chart` | GET | as `/grid/series`, plus `theme` (`light`/`dark`) |
| `/grid/ticks` | GET | `symbol` (one), `limit` (1–1000) |
| `/grid/ta_chart` | GET | `symbol`, `interval`, `source` (`local`/`eodhd`), `macro`, `indicators`, `anchor`, `start`, `end`, `theme`; no `provider` |
| `/grid/ws_ticket` | GET | `target` (one `/grid` socket); desktop `Origin` only |
| `/grid/live_grid_ws` | GET + Upgrade | no query; frames `{"params":{"symbol":"A,B"}}`, each re-validated |
| `/grid/ta_chart_ws` | GET + Upgrade | the `/grid/ta_chart` query is the subscription; no client frames |

`interval` ∈ 1s 5s 15s 30s 1m 5m 15m 30m 1h 4h 1d; on this line history is EODHD's, so only
1m, 5m, 1h and 1d return bars (P2). No route, frame or push is metered (the daily and per-minute budgets were removed
2026-10-17); `FRAME_CAP` = 60 client frames per `live_grid_ws` socket
(tick-chart pushes are not capped); no socket lifetime, a 30 s ping; `maxSockets` applies. With
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
   kdb cache. The donor's S3 tier first appears in a later donor release (78c7af9).
   **These are later donor items, moved into v10 by user ruling.**
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
byte-identical to the donor's latest (main; last substantive commits b6ce372,
93fcd88, 2fc9b6b). The behaviour the tests prove: a dead connection fails its `1+1` liveness
check; the next call walks the chain again to `kdb:5000`; the expiring 60 s latch
(25ba5f7's fix, in b6ce372's session.py) suppresses retries during an outage and picks up a
q that came back; the schema statement is re-issued on the new connection; a flush during
the outage is counted in `dropped` and does not kill the feed. Nothing to take. Not taken:
b569994 (forex feed liveness) and 0cf96ab (drain interval), which are feed tuning, not
restart recovery.

What a restart loses, by design: ticks EODHD sends while live-grid is down (no feed), and a
flush that fails while kdb is down (bounded buffer, counted in `/health` `ticks.dropped`).
The Live Chart's `/series` fills those down minutes at query time (user ruling 2026-10-17,
`app/gapfill.py`): US equities from EODHD's recent closed minute bars (the same EDGX stream,
about the last two traded hours), crypto from intraday 1m; forex stays unfilled. A filled
minute serves 1m and wider widths only, and the ticks themselves (Tick History) keep the hole.
With the S3 tier's read-back on (`LIVE_GRID_LAKE_READBACK`), an intraday request takes the lake path,
which does not fill: the NAS runs with read-back off.

### The S3 tier (724739e)

| Path | Donor commits (tag) | Disposition |
|---|---|---|
| `openbb-deltalake/` (22 files) | 2b02ed7, 0e1b465, c5a06ae, 6dd737b, bf07da0, 9ad866f, 7b40ab1 (2026-09-01); 3b10505, b6653a7 (2026-09-03/04); d999ebe, ed38326; 23f076a (docs); f69689e (openbb-core 2.0.1 floor); headers 78c7af9/2e5af70/b7045aa | ADD, content = `afda165`. Edits: README preface; tests build the example tailnet suffix at run time and use `EXAMPLE_*` secrets so `check-public.py` passes (same assertions). Installed only in the openbq-lake image |
| `scripts/eod_dump.py` | 4b84311, 7fc889b, a061853; 714d43c | ADD, from `afda165`. Edits below |
| `docker-compose.yml` `eod-dump` | ec5e738, 714d43c | ADD, rewritten for this line |
| `docker-compose.yml` `rustfs`, `rustfs-init`, volume `rustfs-data` | shape from a7d5b3e/ec5e738 (`minio`, `minio-init`, `minio-data`) | REPLACED by RustFS (ruling 3) |
| `rustfs.env.example` | minio.env.example (a7d5b3e, b1374ac, d999ebe) | REPLACED: RustFS names, empty secrets, the `DELTA_S3_*` contract kept |
| `eod.env.example` | 714d43c | ADD, hot mirror off |
| `Dockerfile.lake` (`openbq-lake:10.0.0`) | the donor's `openbb-local` image as eod-dump's runtime (ec5e738) | NEW: the counterpart, separate from openbq-api |
| `scripts/s3_init.py` | replaces `minio-init`'s `mc mb --ignore-existing` (a7d5b3e) | NEW, S3 API via pyarrow |
| `live-grid/app/lake.py`, `live-grid/app/main.py` (`build_series(..., lake=)`), `live-grid/pyproject.toml` (+deltalake, pyarrow) | none on the donor line (its live-grid never reads Delta at those commits; its later tick vault is d07898b) | NEW, the read-back (C4) |
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
| 785fef8, 12cfc20 + d75a48d, a5e6f4a: MinIO from release binaries, not withdrawn images | EXCLUDE, superseded by the RustFS ruling |
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
- **C4** PROVISIONAL: the read-back. The donor line has no live-grid reader for flushed
  ticks (its eod-dump comment says the chart's seam reads the hot mirror, but none of its
  code does). `live-grid/app/lake.py` is this line's own: for an intraday interval that tiles a
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
   the count: `docker compose exec live-grid python -c "from openbq_kdb.config import resolve_config; from openbq_kdb.session import KdbSession; from openbq_kdb.store import KdbStore; s=KdbStore(KdbSession(resolve_config())); print(s._call(lambda c: c('count trades').py()))"`
   and `ls` the log: `docker compose exec openbq-kdb ls -l /data/logs`.
2. `docker compose kill -s SIGKILL openbq-kdb`, wait 10 s, `docker compose start openbq-kdb`
   (and once with `docker compose up -d --force-recreate openbq-kdb`, which recreates the container).
3. `docker compose logs openbq-kdb` shows `tlog: replaying tlog_<date>` and `tick log active`.
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
   `rustfs.env` absent or holding `rustfsadmin`, rustfs logs the refusal once and idles
   unhealthy (D22: no restart loop); `docker compose --profile live up -d` reports
   rustfs-init's dependency as failed, and kdb and live-grid run and answer without the store.
   The health check's `curl` is present in `rustfs/rustfs:1.0.1` (checked 2026-10-16 on the
   pinned digest); confirm rustfs turns healthy with `rustfs.env` filled.
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

## Persistent RustFS and the kdb-x build recipe (user request, 2026-10-12)

The user asked to continue building the kdb and RustFS containers and ruled that **RustFS
must be persistent**.

**RustFS persistence (ruling).** The store moved from the named volume `rustfs-data` to a
host directory, `${RUSTFS_DATA_DIR:-./rustfs-data}:/data` (`./rustfs-data/` was already
git-ignored). A named volume already survived container recreation, but `docker compose down -v`
deleted it, and it was not a plain directory an operator could back up or move. The host
directory survives recreation, image upgrades and `down -v`, and can sit on any disk.
The RustFS image runs as `rustfs` (uid/gid 10001; upstream `Dockerfile` at 1.0.1:
`USER rustfs`, `chown -R rustfs:rustfs /data`). That chown only reaches the image layer, not a
bind mount, so a new one-shot, `rustfs-perms`, runs first: the lake image as root, with
`network_mode: none`, creates the directory and chowns it to 10001:10001 only when the owner
is wrong. `rustfs` waits for it (`service_completed_successfully`). No new image.
REVIEW: `tests/test_lake_profile.py` asserted `rustfs-data:/data` and the named volume; it
now asserts the host bind and that no named volume remains. New test:
`test_rustfs_data_is_a_host_directory_made_writable_before_rustfs_starts`.
kdb's tick logs stay on the named volume `kdb-data` (C1); moving them to a host directory the
same way is an open option for the user.

**kdb-x build recipe.** Ported from bdobb-dev/openbb-docker v10.1.7: `kdb-x/Dockerfile`,
`kdb-x/entrypoint.sh`, `kdb-x/README.md` (donor 1ab20f1, e12fce1, e520b60, baee69b; the
directory was excluded from the first v10 pass). It ships no KX software: the build downloads
KDB-X from KX's portal (`KX_VERSION`, default `~latest~`), deletes any licence in the same
layer, and fails on a wrong-architecture `q`. `docker-compose.yml` keeps
`ghcr.io/artcashin/kdb-x:amd64` (the ruling's image); the new override `compose.kdb-build.yml`
builds from `kdb-x/` and tags `openbq-kdb-x:local`, changing nothing else about `kdb`. A
README section covers its use in this stack. New tests: `tests/test_kdb_build.py` (4).

**Not done in the cloud.** Starting a Docker daemon in the cloud container was refused by the
session's sandbox, so no image was built, pulled or run. Mac steps:
1. `docker compose -f docker-compose.yml -f compose.kdb-build.yml --profile live build kdb`
   (and `docker buildx build --platform linux/amd64,linux/arm64 kdb-x/` if a multi-arch image
   is wanted); the build log ends with `no licence present`.
2. `docker compose --profile live build` (openbq-lake, live-grid) and `up -d`; `rustfs-perms`
   exits 0 and `./rustfs-data` (or `$RUSTFS_DATA_DIR`) is owned by 10001:10001.
3. Persistence: write an object (or run step 4.2 above), then `docker compose --profile live
   down -v && docker compose --profile live up -d`: the object and the flushed Delta tables
   are still there, rustfs-init is still idempotent, and the read-back still reports
   `lake_days`.

Receipts (cloud): `tests/` 32 passed (was 28: +1 lake, +4 kdb build, one assertion changed
with REVIEW), check-public PASS, `docker compose config` valid for the default stack (only
`openbq-api`, `tailscale`), `--profile live`, `RUSTFS_DATA_DIR=/srv/lake`, and with the
kdb-build override.

## The licence directory is configurable (user, 2026-10-12)

The user keeps the kdb licence outside this repository (in a private checkout beside this one; first named as bdobb-dev/openbb-kdb, corrected by the user). The three
services that mount it (kdb, live-grid, eod-dump) now take
`${KDB_LICENSE_DIR:-./kdb-license}:/opt/kx-license:ro`, so a private checkout kept beside this
one can be used directly (`KDB_LICENSE_DIR=../openbb-kdb/<dir>` in the shell or `.env`) and
the licence is never copied into this repository. The default is unchanged. `.env.example` carries the setting commented out with a generic `./kdb-license` (D9, 2026-10-16: an uncommented home path there overrode the default for every reader who copied it). The licence was
not fetched into the cloud session (the user's ruling: no licence in chat or cloud).
REVIEW: three mount assertions now name the variable; a new test checks that exactly those
three services share the one read-only mount. Tests: `tests/` 33 passed.

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

## Tick spool and fast reconnect (user ruling, 2026-10-12)

### The finding (Mac, 2026-10-12)

The user ran the `live` profile on the Mac with a licensed KDB-X and EODHD and did the
crash-recovery drill above:

| Step | kdb `count trades` |
|---|---|
| before `docker compose kill -s SIGKILL kdb` | 1948 |
| after `docker compose start kdb` (log: `tlog: replaying tlog_2026.10.12`) | 1948 |
| 60 s later | 2435 |

kdb's own recovery (kdb-ws/persist.q) works. But live-grid's `/health` read
`{'buffered': 0, 'written': 2436, 'dropped': 2459, 'endpoint': 'loopback'}`. While kdb was
down, live-grid **dropped** about 100 s of BTC-USD and ETH-USD ticks (about 24 ticks/s),
for two reasons:

- `TickRecorder.flush` discarded every batch whose write failed. That was the donor's
  design: a cache was never promised to keep ticks.
- kdb-store's `KdbSession` latched every connect attempt off for a fixed 60 s after one
  failure (`_RETRY_AFTER_S`), so live-grid sat out a whole minute after a kdb restart that
  took seconds.

The same read showed a third, smaller loss. `flush` copied the buffer, wrote the copy, then
cleared the buffer. A tick that `record()` (on the event loop) appended during the write
(on a worker thread) was cleared without being written or counted.

### The ruling

**Ticks must be spooled to the filesystem and recovered when a service restarts.** This is
a user ruling, given in this session on 2026-10-12. It is not provisional.

### Design

**Where.** `live-grid/app/spool.py`, under `LIVE_GRID_SPOOL_DIR`. Compose sets
`/data/spool`, on the persistent named volume `live-grid-data`, beside the watchlist. With
the variable unset, the spool is a `spool/` directory next to `LIVE_GRID_WATCHLIST`. The
directory is created on the first append.

**Format.** Append-only JSON lines in `ticks_<UTC date>_<seq>.jsonl`, one compact array
per tick: `["2026-10-12T14:00:00.123456+00:00","BTC-USD",62000.5,0.001]`. A fifth element,
a batch id, marks the lines of an in-doubt batch. The date is the UTC date the tick was
spooled, not the tick's own stamp. `seq` (six digits) rises with every file opened that
day: at startup, and at each roll (an eighth of the cap, at most 16 MB). A lexical sort of
the names is therefore append order, and replay frees disk a file at a time while a
backlog drains. JSON lines rather than a binary format, for three reasons:

- it is about 70 bytes a tick, so the default cap holds about 3.8 M ticks (about 44 h at
  the drill's 24 ticks/s);
- a torn final line is detectable, and is cut at startup and counted as dropped;
- prices and stamps round-trip exactly (`repr` floats, ISO stamps with their UTC offset),
  which the duplicate probe below relies on.

**When.** Spooling depends on how a direct write to kdb fails:

- `KdbUnavailable` is raised before anything is sent, so the batch is spooled as plain
  lines.
- Any other exception means the batch may have reached kdb, so it is spooled as one
  in-doubt batch.

While the spool holds anything, every new batch is appended to its tail rather than
written to kdb. kdb therefore receives ticks in arrival order: the backlog first, then the
live ticks.

**Replay.** Every flush (every 0.2 s) replays the spool oldest first. A segment is up to
5,000 plain lines, or one whole in-doubt batch; the two are never mixed or split. Each
flush spends about 1 s at most, so a long backlog does not stall quote draining. For each
segment:

1. **Stage.** The cursor `spool.state` (`{file, offset, inflight}`) records
   `inflight = segment end`. It is written to a temp file, fsynced, renamed, and the
   directory is fsynced. This happens before any byte goes to kdb.
2. **Send.** `write_ticks` sends the segment as one batch.
3. **Acknowledge.** Only after kdb confirms: `offset` advances and `inflight` is cleared.
   A file is deleted only once every line in it is acknowledged.

If the send raises `KdbUnavailable`, nothing was sent, so the segment is unstaged; it
stays in doubt only if it already was. Any other exception leaves it staged, so it is in
doubt next time. While the session is backing off (`KdbSession.retry_in() > 0`), no
replay is staged, so an outage costs no cursor fsync per flush.

**Startup.** `TickSpool` counts what an earlier process left (streamed, not read into
memory) and cuts any torn tail. The first flush replays the leftovers before any new tick.
A graceful stop (`docker compose stop` or `restart`) also spools the unflushed buffer. A
SIGKILL loses only the in-memory buffer of at most 0.2 s, plus the ticks the feed sends
while live-grid is down, which it never receives.

**Durability.** Every append is written through to the OS (`flush()`), so a killed
live-grid loses nothing that reached the spool. fsync runs at most once per
`LIVE_GRID_SPOOL_FSYNC_S` (default 1 s), from `append` or from `sync()`. The recorder calls
`sync()` on every flush, so an idle spool is synced within that interval plus 0.2 s. A host
crash or power loss can therefore cost about the last second of appends. The cursor is
fsynced on every change, which is once per replayed segment and never once per tick.

**Duplicates.** The spool holds only ticks kdb never acknowledged, and persist.q replays
only what kdb itself logged. The two overlap only for an **in-doubt** segment: one sent to
a kdb that applied it and then died before replying, or one staged when live-grid itself
died after kdb confirmed but before the acknowledgement. A batch lands all or nothing:

- `write_ticks` applies it in one `upd` (or `insert`) message;
- persist.q logs that message before applying it;
- so a q killed half way through replays the whole batch at boot.

The recorder therefore probes before re-sending an in-doubt segment.
`KdbStore.ticks_present(frame)` counts the segment's rows found in `trades`, matching all
four columns, within the segment's own time window. If every row is present, the segment
is acknowledged without being sent and counted in `deduped`. Otherwise it is sent. In the
normal path (kdb unreachable, so `KdbUnavailable`) nothing is in doubt and no probe runs.
That every tick lands exactly once is proved by the tests below. Two limits apply:

- An in-doubt segment that was **not** applied, but whose every row already exists in
  `trades` at least as many times as the segment holds it (identical time, sym, price and
  size), would be skipped. EODHD's crypto feed repeats byte-identical prints (below: 1,509
  distinct of 2,588 in 30 s, groups up to 59), so the probe counts rows as a multiset
  (D17, 2026-10-16; a plain find made one twin per row enough). What remains is a run of
  repeats split across two batches, the earlier applied with at least as many copies as
  the in-doubt one; only a batch id in `trades` would close it.
- A segment whose ticks have since been pruned (older than the 1-day window) would be
  re-sent and then pruned again.

**Bounded.** `LIVE_GRID_SPOOL_MAX_MB` (default 256) caps the total size of the tick files.
Past the cap, the newest ticks are refused, so the spool's order stays intact. They are
counted in `dropped`, and the first refusal of a run is logged as a warning. An I/O error
(for example ENOSPC) is handled the same way, and a partly written line is cut back so the
next append starts clean. The disk is never filled silently.

**`/health` `ticks`.** It now carries `buffered`, `written`, `dropped`, `spooled`,
`replayed`, `deduped` and `endpoint`:

- `spooled` is the number of ticks on disk now.
- `replayed` and `deduped` count since the process started.
- `written` counts every tick kdb confirmed, including the replayed ones.
- `dropped` counts only ticks truly lost: buffer overflow, the spool cap, or a spool I/O
  error. Without a spool, the class's library default, it also counts a failed batch; the
  donor's recorder tests pin that path.

**Fast reconnect.** kdb-store `session.py` replaces the fixed 60 s latch with a backoff:
1 s after the first failed connect, doubling per consecutive failure, capped at 15 s
(`KDB_RETRY_INITIAL_S`, `KDB_RETRY_MAX_S`, read at each failure). The first success resets
it. What the latch protected is kept:

- It is still a **deadline**, so the hazard stays bounded as a rate, never a count. That
  is the comment's point about the donor's cold-start race, where live-grid's drain loop
  reaches q before openbb-api has bound :5000.
- Every call inside the window still fails fast without dialling q.
- In steady failure, attempts converge to one per 15 s.

The worst cases, against the old 60 s:

- A reader with no licence pays a doomed spawn once per 15 s instead of once per 60 s.
  `poll()` makes that a few milliseconds.
- A loopback port squatted by a non-q listener (macOS AirPlay on :5000) holds the owner
  thread for the 5 s connect budget once per 20 s, not once per 65 s.

In this stack live-grid never spawns (`KDB_EMBEDDED=false`) and dials `kdb:5000` on the
bridge, so neither case applies here. `KdbSession` takes an injectable clock.

**The flush race** is fixed. `flush` now pops exactly the ticks it takes
(`deque.popleft`), so a tick recorded during a write stays buffered for the next flush.

### Commits

| Commit | What |
|---|---|
| `2718052` | kdb-store: the exponential backoff, `test_backoff.py` |
| `f60a0df` | kdb-store: `ticks_present`; the kdb-ws simulator models the probe and a q that dies after applying an upd |
| `4f4c627` | kdb-store: `KdbSession.retry_in` |
| `8fcf04a` | live-grid: `app/spool.py`, the recorder, `/health`, the flush-race fix, `tests/test_spool.py` |
| `9b98f50` | compose: the spool and backoff variables; `tests/test_live_profile.py` |
| the docs commit after it | this section, live-grid/README.md, `kdb-store/scripts/tick_check.py` (real-q checks of `ticks_present`) |

New compose variables on `live-grid` (each commented in `docker-compose.yml`):
`LIVE_GRID_SPOOL_DIR=/data/spool`, `LIVE_GRID_SPOOL_MAX_MB=256`,
`LIVE_GRID_SPOOL_FSYNC_S=1`, `KDB_RETRY_INITIAL_S=1`, `KDB_RETRY_MAX_S=15`.

### Tests and REVIEW notes

The new tests run against the kdb-ws simulator (startup.q + persist.q, its log and boot
replay), with the real `KdbSession`, `KdbStore`, `TickRecorder` and `TickSpool`. Only
`_connect` and the session clock are replaced. There is no q binary here.

- `live-grid/tests/test_spool.py` (22 tests):
  - a kdb outage mid-stream spools 250 ticks with `dropped` 0; after the restart, every
    tick is in kdb exactly once, in feed order, with live ticks behind the backlog; a
    second kdb restart replays the same set from kdb's log;
  - reconnect happens 1 s after the refusal, not 60 s;
  - no replay is staged during backoff;
  - an in-doubt live write that kdb applied before dying is deduped; one it did not apply
    is sent;
  - an in-doubt replay write is deduped;
  - a live-grid killed with a non-empty spool replays it on its first flush;
  - a live-grid killed between kdb's confirmation and the acknowledgement does not
    duplicate the staged segment;
  - through `create_app`, `/health` shows `replayed` 30, `spooled` 0, `dropped` 0;
  - a graceful stop stashes the buffer;
  - the cap is honoured and counted, keeping the oldest ticks;
  - the cap, fsync interval and directory come from the environment; the default
    directory sits beside the watchlist;
  - the fsync cadence holds under an injected clock;
  - a torn tail is cut;
  - files replay oldest first and are deleted only after the acknowledgement; files roll
    by size and free disk while a backlog drains;
  - in-doubt batches are never merged with plain lines;
  - an ENOSPC part way through a write leaves no partial line;
  - the flush race;
  - replayed frames are identical to live ones.
- `kdb-store/tests/test_backoff.py` (10 tests), with an injected clock: the delays are
  1, 2, 4, 8, 15, 15 s; under a 0.25 s poll for 60 s, attempts land at
  0, 1, 3, 7, 15, 30, 45 and 60 s; calls inside the window do not dial; success resets
  the backoff; the environment overrides work and bad values fall back; a cap of 0
  disables the latch; `retry_in`.
- `kdb-store/tests/test_store.py` +2 (the probe's statement and cleanup; no q call for an
  empty frame). `kdb-store/tests/test_crash_recovery.py` +1 (an in-doubt write is resolved
  by `ticks_present` after the restart).
- `tests/test_live_profile.py` +1: the spool is on `live-grid-data` and bounded, and the
  backoff is 1 s and 15 s.
- REVIEW `live-grid/tests/test_main.py`
  `test_health_includes_ticks_key_when_chart_is_enabled_by_default`: the exact key set
  `{buffered, written, dropped, endpoint}` becomes
  `{buffered, written, dropped, endpoint, spooled, replayed, deduped}`. It is still an
  exact set, so it is not weakened.
- Unchanged and still green, because they pin the spool-less recorder (the class default):
  `live-grid/tests/test_recorder.py` (a failed flush drops and counts the batch) and
  `live-grid/tests/test_crash_recovery.py`
  `test_a_kdb_killed_mid_session_comes_back_with_the_day_and_recording_resumes`
  (`dropped == 5` during the outage, with `_RETRY_AFTER_S` patched to 0). Production
  always passes a spool (`app/main.py`).
- The older latch tests (`test_session.py`, `test_crash_recovery.py`) patch the module's
  `_RETRY_AFTER_S`, which is now the cap. They pass unchanged. In
  `test_the_retry_latch_holds_off_then_picks_up_a_q_that_came_back` the window that holds
  off is now the 1 s first step, where it was 60 s.
- Test infrastructure: `live-grid/tests/conftest.py` gains an autouse fixture that points
  `LIVE_GRID_SPOOL_DIR` at `tmp_path`, so no test writes to a real `/data`. The kdb-ws
  simulator parses mixed-precision ISO stamps in its own log; `isoformat()` drops a zero
  microsecond part.

Receipts (cloud, 2026-10-12): `live-grid` 452 passed, 14 deselected (`lg312`,
`-m "not network"`; was 430); `kdb-store` 143 passed (was 130; `lg312` and `kdb312`);
`kdb-ws/tests` 9; `tests/` 34 passed, 5 subtests (was 33); `v3/tests` 68, `lanes/tests` 22,
`workspace/tests` 12 (`img312`); `scripts/check-public.py` PASS. No test was skipped,
deleted or weakened. EODHD calls: 0. Nothing was pushed, built or run, and no docker
command was run.

### Mac drill, revised

The first run needs a rebuild of live-grid; kdb-store is copied into its image:
`docker compose --profile live build live-grid && docker compose --profile live up -d`.
**After** drills A to C (not before: its last step, `prune_ticks(2030)`, empties `trades`
in kdb's memory; the tick log keeps the rows, and a kdb restart brings them back), run
`v10/kdb/source/scripts/tick_check.py` against the real q:
`docker compose cp v10/kdb/source/scripts/tick_check.py live-grid:/tmp/ && docker compose exec
live-grid python /tmp/tick_check.py`. It must report `FAILURES: none`, including the new
`ticks_present` checks. `ticks_present` is the one statement the cloud could only
simulate. Then run `docker compose restart openbq-kdb` to restore the day from the log. The
script's own `TICKCHK` rows come back too; they are dated 2025-06-10, so live-grid's next
rolling-window prune drops them.

Helpers, pasted once into the shell. `/health` takes the API's Basic pair when
`OPENBB_API_AUTH=true`.

```sh
lg_ticks() { docker compose exec -T live-grid python - <<'PY'
import base64, json, os, urllib.request as u
r = u.Request("http://127.0.0.1:6903/health")
if os.environ.get("OPENBB_API_USERNAME"):
    pair = f"{os.environ['OPENBB_API_USERNAME']}:{os.environ.get('OPENBB_API_PASSWORD', '')}"
    r.add_header("Authorization", "Basic " + base64.b64encode(pair.encode()).decode())
print(json.load(u.urlopen(r))["ticks"])
PY
}
kdb_count() { docker compose exec -T live-grid python - <<'PY'
from openbq_kdb.config import resolve_config
from openbq_kdb.session import KdbSession
from openbq_kdb.store import KdbStore
s = KdbStore(KdbSession(resolve_config()))
print(s._call(lambda c: c("(count trades; count distinct select time, sym, price, size from trades)").py()))
s.session.close()
PY
}
```

`kdb_count` prints `[rows, distinct rows]`; the distinct count is informational only (see the note under A's pass criteria).

**A. kdb killed mid-session** (crypto in the watchlist, so ticks flow at any hour).

1. `kdb_count; lg_ticks`. Note `C0` (the rows), the distinct count `D0`, and `W0`
   (`written`).
2. `docker compose kill -s SIGKILL openbq-kdb`, then wait 100 s. During the wait, `lg_ticks`
   shows `spooled` rising (about 24/s) and `dropped` 0. `docker compose exec live-grid
   ls -l /data/spool` shows `ticks_<date>_000000.jsonl`.
3. `docker compose start openbq-kdb`. `docker compose logs openbq-kdb | grep tlog` shows
   `tlog: replaying tlog_<date>`.
4. Within a few seconds (backoff of at most 15 s; usually the next 1 to 8 s step):
   `lg_ticks` shows `spooled` 0, `replayed` about equal to the step-2 peak, and `dropped`
   0. `docker compose logs live-grid | grep "tick spool"` shows `replayed N ticks`.
5. Wait 60 s, then `kdb_count; lg_ticks` again for `C1`, `D1` and `W1`.

**Pass criteria for A.**

- `dropped: 0`;
- `C1 - C0 == W1 - W0`: every tick live-grid wrote, including the outage's, is in kdb;
- the final count covers the outage: `C1 - C0` is roughly (100 s + 60 s) × 24 ticks/s,
  not 60 s × 24;
- no distinct-row criterion. EODHD's crypto feed itself repeats byte-identical trade messages (no trade id or venue in a message): measured 2026-10-13, 30 s of BTC-USD and ETH-USD raw from EODHD gave 2,588 trades, 1,509 distinct (time, sym, price, size), groups up to 59; the Mac kdb showed the same shape (groups up to 70). kdb stores what the feed sends, so `C1 - C0 == W1 - W0` (with `deduped` for any in-doubt batch) is the test that nothing was written twice;
- the kdb log shows the `tlog: replaying` line.

Repeat once with `docker compose up -d --force-recreate openbq-kdb` in place of `start`.

**Receipt, drill A (Mac, 2026-10-13, `drill-a.sh`, branch at 83690fa).** live-grid
rebuilt as `openbq-live-grid:10.0.0`; `/health` carries `spooled`, `replayed` and
`deduped`. BTC-USD and ETH-USD leased; kdb SIGKILLed for 100 s.

| | rows | written | dropped | spooled | replayed | endpoint |
|---|---|---|---|---|---|---|
| before | 191752 | 4903..5246 | 0 | 0 | 0 | loopback |
| +20 s .. +100 s | | 5246 | 0 | 2032 → 11221 | | None |
| after (+60 s) | 220807 | 34279..34346 | 0 | 0 | 15320 | loopback |

Verdict PASS on all five: `dropped` flat at 0; spool peaked at 11221 and drained to 0;
kdb rows rose 29055, inside the bracketed `written` delta 29033..29443; kdb reconnected;
kdb logged `tlog: replaying tlog_2026.10.13`. `deduped` 0 (no in-doubt batch). Compare
drill 1 on the pre-spool build: 2,459 dropped and a 60 s reconnect latch. Still to run:
the `--force-recreate` variant, B, C and `tick_check.py`.

**B. live-grid SIGKILLed mid-outage.**

1. `kdb_count; lg_ticks`. Note `C0`, `D0` and `W0`.
2. `docker compose kill -s SIGKILL openbq-kdb`, then wait 30 s. `lg_ticks` shows `spooled` `S`
   (about 700) and `W1` (`written`, unchanged since kdb died).
3. `docker compose kill -s SIGKILL live-grid`, then wait 10 s, then
   `docker compose start live-grid`.
4. `lg_ticks` (the new process; kdb is still down): `spooled` ≥ `S`, because the
   leftovers were counted at startup and new ticks are added to them. `replayed` is 0 and
   `dropped` is 0. `docker compose logs live-grid | grep "left by a previous run"`.
5. `docker compose start openbq-kdb`. Within a few seconds `lg_ticks` shows `spooled` 0,
   `replayed` ≥ `S` and `dropped` 0.
6. Wait 60 s, then `kdb_count; lg_ticks` for `C2`, `D2` and `W2` (the new process's
   `written`).

**Pass criteria for B.**

- `dropped: 0` in both processes;
- `C2 - C0 == (W1 - W0) + W2`;
- no distinct-row criterion (see A);
- the kdb log shows `tlog: replaying`.

The only gap allowed is the 10 s live-grid was down, whose ticks it never received, plus
at most its 0.2 s in-memory buffer at the SIGKILL.

**C. Graceful.** `docker compose --profile live restart` gives `dropped: 0`, and the new
process's `replayed` covers any ticks it stashed at stop.

**Receipt, drills B and C (Mac, 2026-10-13, `drill-bc.sh`, live-grid from 83690fa).**

B: before, rows 318398 and `written` 131874..131891. kdb SIGKILLed; after 30 s `written`
131891 (frozen), `spooled` 3572, `dropped` 0. live-grid SIGKILLed, down 10 s, restarted with
kdb still down: the new process logged `tick spool: 3587 ticks left by a previous run in
/data/spool; replaying them first`, showed `spooled` 3595, `replayed` 0, `dropped` 0. kdb
started (`tlog: replaying tlog_2026.10.13`); after 60 s rows 332939, new `written`
14521..14541, `spooled` 0, `replayed` 4144, `deduped` 0, `dropped` 0. Rows rose 14541,
inside the bracket 14521..14558 for (old written) + (new written). PASS on all nine checks.

C: `docker compose --profile live restart` (all nine running containers, 4 s). Rows
333448 → 337422 (+3974); the new process's `written` 3963..3974, `dropped` 0, `spooled` 0,
`replayed` 0. Lower bound 3963 and upper bound 4275 both hold: PASS. Limit of this check:
ticks the old process wrote in the second or so between the script's last read and the
stop are inside the upper slack, so a loss confined to that window would not show; the
delta here (+3974 against a final read of 3974) leaves no room for one of more than about
a dozen ticks.

Still to run: drill A with `--force-recreate`.

**Receipt, `tick_check.py` (Mac, 2026-10-13, real KDB-X Community Edition q, endpoint
loopback).** 23 checks, `FAILURES: none`, including the four `ticks_present` checks the
cloud could only simulate (a written batch all present, 4; an unwritten batch absent, 0;
row-by-row counting, 2; absent before and present after a tz-aware write in live-grid's
shape, 0 then 2). Followed by `docker compose restart kdb` to reload the day from the tick
log.

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

## Subscriptions through the gateway (V10-P5, user request 2026-10-13)

The example dashboard's Subscriptions card (live-grid's `/subscriptions` iframe page) now works
through the gateway, the option V10-P5 named. live-grid still has no host port (P3).

- `funnel-gateway/server.mjs`:
  - `GET /grid/subscriptions` serves the page;
  - `GET`/`POST /grid/api/subscriptions` and `DELETE /grid/api/subscriptions/<symbol>` relay
    the watchlist API;
  - `/grid/widgets.json` rewrites the `subscriptions` widget's endpoint to
    `<origin>/grid/subscriptions`.
- **PROVISIONAL, server P8: the page is served without the Bearer token.** It is the one
  exception to "the lock precedes everything". A frame is a navigation and cannot carry a
  header; BDOBB has no ticket for frames. The exception is narrow: exact path, GET, no query,
  no body, this door's Host. The page is fetched from live-grid once and served from memory,
  so an anonymous caller costs no upstream dial. It holds no data;
  every watchlist call is behind the lock. The page gets the Bearer header from BDOBB's
  `openbb-connect` → `openbb-auth` handshake, which BDOBB sends only to a frame on the
  backend's own origin. Alternative if this is not acceptable: a frame ticket, which would
  need a BDOBB change.
- POST is not metered. The body is rebuilt
  from the validated one-symbol grammar. live-grid's 404/409/422/507 come back as the door's
  own messages.
- Not in `policy.mjs`, which BDOBB's web layer vendors under a hash test. The web preview
  cannot use the card: its browser never holds the token. The desktop app can.
- `live-grid/app/static/subscriptions.html`: the API path is resolved relative to the page; when
  framed, the page asks the parent for the credential (2 s timeout; only `window.parent` is
  trusted). `^` stays literal in a DELETE path.
- `docker-compose.yml`: `LIVE_GRID_PUBLIC_URL: ${LIVE_GRID_PUBLIC_URL:-http://live-grid:6903}`,
  so live-grid publishes the widget for the gateway to reframe.
  Superseded in the v10 carry (2026-10-17): the default is empty and live-grid names the page
  by the request's own scheme and host, so a direct connection is not handed the internal
  hostname; the gateway rewrite is unchanged.
- A direct HTTPS tailnet Serve to live-grid must set `LIVE_GRID_PUBLIC_URL` to its `https://` address.
  TLS ends before live-grid, so without it the iframe URL comes out `http://` and the page's
  POST/DELETE writes get 403 on the Origin check.
- REVIEW `verify.mjs`: `/grid/api/subscriptions` with the token moves from "refused 404" (it
  is a route now) to the without-token 401 list. New refusals prove the exception narrow:
  `/grid/subscriptions?x=1` and `/grid/subscriptions/` without the token are 401; the watchlist
  API's query, nested-path and GET-one-symbol shapes are 404 with it. The page is not probed to
  200, because that would dial live-grid.
- REVIEW `live-grid/tests/test_auth_routes.py`
  `test_the_page_and_its_api_share_one_origin`: `"/api/subscriptions" in page.text` would
  now pass on a comment alone. It becomes a check for the relative resolution, plus checks that
  no call names the root-absolute path. Stronger, not weaker.

Receipts (cloud): funnel-gateway 88 passed (was 77; +11); live-grid 454 passed, 14 deselected
(+1 for the handshake); `tests/` 35 passed (+1); `scripts/check-public.py` PASS. Not run: the
desktop app framing the page (Mac).

## Renamed openbq-kdb (2026-10-14, user ruling)

User ruling: "openbq-docker v10 should have openbq-kdb" and "it should be Adventures-OpenBQ/openbq-kdb". The kdb tier now lives in its own repository, Adventures-OpenBQ/openbq-kdb, which this stack vendors under `v10/kdb/source`, as it vendors openbq-yfinance and openbq-eodhd.
- The repository's first commit (9519bbc, tag `v10.0.0`) imports `kdb-store/` and `kdb-ws/` as of fc70ffc and renames them. `v10/kdb/source` is `git archive v10.0.0` of that repository, and `v10/kdb/source.json` records the repository, tag, commit and version, with the donor (bdobb-dev/openbb-docker v10.1.7 d606169) in a donor block.
- Renamed:
  - `kdb-store` → `openbq-kdb`, module `kdb_store` → `openbq_kdb` (live-grid's imports, `monkeypatch` targets and its `pyproject.toml` dependency), version 10.0.0;
  - `kdb-ws/` → `q/` inside the package (`startup.q`, `persist.q`, `gen.q`, `live-chart.html`, the tick-plant model `q/tests/tickplant_sim.py`, whose path live-grid's tests now read from `v10/kdb/source/q/tests/`);
  - the compose service `kdb` → `openbq-kdb` (`docker-compose.yml`, `compose.kdb-build.yml`, live-grid's `KDB_BIND_HOST` and eod-dump's `KDB_HOST`);
  - the container paths `/opt/kdb-ws/*` → `/opt/openbq-kdb/*`;
  - live-grid's Dockerfile `COPY` lines.
- Not renamed:
  - the `ghcr.io/artcashin/kdb-x:amd64` image and the `kdb-x/` recipe (a third-party runtime, per the ruling);
  - the local build tag `openbq-kdb-x:local`.
- PROVISIONAL:
  - the named volume `kdb-data` keeps its name, so existing tick logs survive the rename;
  - the `KDB_*` environment variables (`KDB_LICENSE_DIR`, `KDB_PORT`, `KDB_HOST`, `KDB_BIND_HOST`, `KDB_PERSIST_Q`) keep their names, so operators' `.env` files keep working;
  - the version is 10.0.0, matching the episode, instead of the donor's 10.1.0.
- REVIEW, assertions changed for the rename, none weakened. Each asserts the same fact under the new name or path:
  - `tests/test_live_profile.py`: the `LIVE` tuple, the image and licence test, the crash-recovery test (mounts, command, `KDB_PERSIST_Q`, the startup.q path), the tick-log volume test, the restart test, live-grid's `KDB_BIND_HOST`, and the licence-mount users;
  - `tests/test_kdb_build.py`: the override's service key, and the base service and its command;
  - `tests/test_lake_profile.py`: eod-dump's `KDB_HOST`.
- Operators: a running stack started before the rename has a container for the service `kdb`. After the update, `docker compose --profile live up -d --remove-orphans` starts `openbq-kdb` on the same `kdb-data` volume and replays the day's tick log.
- Tests (cloud):
  - `tests/` 38 passed (+5 subtests);
  - live-grid 454 passed, 14 network tests deselected (openbq-kdb installed in place of kdb-store);
  - `v10/kdb/source` 143, `q/tests` 9, openbb-deltalake 95, `scripts/tests` 13;
  - v3 68, lanes 22, workspace 12, `v9/eodhd` 9, provider-fixes 42, funnel-gateway 88;
  - check-public and verify-app-layouts pass.

## Desktop socket tickets (V10-P1, user ruling 2026-10-15)

User ruling: alternative 1, packaged origins only. Not provisional.

- **What was wrong.** Tauri's http plugin (2.5.9, built without `unsafe-headers`) stamps the
  webview's Origin on every request: `tauri://localhost` on macOS, iOS and Linux,
  `http://tauri.localhost` on Windows. The gateway refused any Origin but its own with 403, Bearer
  or not, so the desktop app reached no `/grid` route at all, the snapshot and the documents
  included. The earlier note that `/grid` with a Bearer header served the desktop the snapshot
  was wrong. A probe of the real `createGateway` showed 200 with no Origin and 403 with each
  desktop origin.
- **`server.mjs`.** `DESKTOP_ORIGINS` = exactly those two origins. They pass the HTTP Origin rule
  behind the Bearer lock (no token is still 401; `http://localhost:1420` is still 403).
  `GET /grid/ws_ticket?target=<socket>` (Bearer, desktop Origin only, one `/grid` socket per
  `socketTarget()`) mints a thirty-second single-use ticket with `policy.mjs` `socketTicket`,
  signed over `<Origin><target>`. The upgrade handler admits a ticket from a desktop Origin by
  verifying over that same string, and needs no `previewOrigin`. Preview tickets verify as
  before. The Bearer upgrade path is unchanged (its Origin must still be the gateway's own).
  `policy.mjs` is untouched, so the web layer's vendored copy stays valid.
- **live-grid upstream unchanged.** `connectGrid` presents the stack's Basic pair whichever way
  the client was admitted; live-grid's `auth.py` is not involved.
- **Tests.** `gateway.test.mjs`: three new tests (desktop origins on HTTP, the mint-and-open
  round trip bound to Origin, target and single use, the endpoint's refusals). Local run, node
  26.10.0: 90 of 91 pass; the failure, "DELETE takes one symbol in the path", fails identically
  (421) on the untouched base 72834aa. (Since superseded: after the 2026-10-16 review fixes all 132 gateway tests pass.)
- **Client.** BDOBB `claude/v10-grid-socket-ticket` 1a310c6 fetches a ticket before every
  connect when the backend's credential is a header; its OPEN-QUESTIONS records V10-P1 resolved.
- **Not run.** The packaged app against a running gateway (Mac).
