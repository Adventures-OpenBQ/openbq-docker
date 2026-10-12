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
| this commit | this ledger, README |

## Ported paths

### live-grid, kdb-store, kdb-ws (content = the donor tree at d606169)

| Area | Donor commits (substantive, in v9.6.3..v10.1.7 unless marked) | Disposition |
|---|---|---|
| `kdb-store/` (15 files) | 446e8ca extraction; b6ce372 configurable bind; 93fcd88 tick reader (v10.1.0); b92dc97 fixed-width buckets (v10.1.4); headers a10ac7d/e520b60/baee69b | ADD, verbatim |
| `kdb-ws/` (7 files) | fba775a websocket publish; 3ece955 avwap buckets; d26effb tick log; f6857e1 + 201287e stats wmax/mphy (v10.1.5) | ADD, verbatim. `startup.q`/`persist.q` are what the kdb service runs; `live-chart.html` is copied into live-grid's image; `smoke.mjs`/`run-test.sh`/`gen.q` need a real q (Mac-pending) |
| `kdb-license/.gitkeep` | 59a9b96 | ADD (mount point only) |
| `live-grid/app/` | f15e08f base service; 0cea89c Basic auth; 8d852f0 /symbol_meta; e2789ee subscriptions; cd28309 unified chart; 938ee74 history by asset class; 93fcd88 /ticks and day levels (v10.1.0); 369074e /apps.json (v10.1.0); 7202f75 /health subscriptions reason (v10.1.4); b92dc97 series buckets (v10.1.4); the ta series (4fb851f, 4207888, 2f684bb, 10bfc04, f2d242a, 349aac4, 934bdf5, b26d198, 2c343b4) | ADD; one edit (`openbb_client.py`, below) |
| `live-grid/widgets.json` | f87018a column widths (v10.1.1) | ADD, verbatim |
| `live-grid/apps.json` | 7202f75 (v10.1.4, #72); 369074e serves it | ADD, verbatim (sha256 `26be230f…046d`, identical to the donor) |
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
- `kdb`: `ghcr.io/artcashin/kdb-x:amd64`, `command: ["/data/startup.q"]`, `KX_PORT=5000`
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
| deltalake, minio, security-master, mcp_charts/charts-mcp, stores-explorer, sip-backfill | Out of scope; live-grid imports none of them. |
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
   `./kdb-data`, because the operator puts `startup.q` there.
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
