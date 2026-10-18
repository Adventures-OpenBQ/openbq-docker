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
