<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v10.0.0 release receipt (2026-10-14)

Gated tree: `e6cb490` (`claude/openbq-docker-v10`). This receipt commit changes only this file. `release/v10` contains `release/v9` = v9.0.0 `e6826b1`, through merge `e6cb490`. User order: "tag openbq-docker v10.0.0 and re-pin bdobb".

## What v10.0.0 adds over v9.0.0

- **The live grid** (Episode 10). The `live-grid` FastAPI sidecar serves a ticking quote grid, `/symbol_meta`, series and charts, and its own `apps.json`. Its history comes from EODHD through `OPENBB_HISTORY_NAMESPACE=eodhd`, so every chart call is metered. Ticks are spooled to the `live-grid-data` volume and replayed exactly once after an outage (user ruling 2026-10-12). Reconnects back off from 1 s to 15 s.
- **The kdb+ tick tier, openbq-kdb 10.0.0.** It is vendored in `v10/kdb/source/` from Adventures-OpenBQ/openbq-kdb at `9519bbc`. That tree is byte-identical to the vendored one, path for path and blob for blob. `v10/kdb/source.json` names that commit and the tag `v10.0.0`.
  - The package is this line's `kdb-store/` and `kdb-ws/`, renamed `openbq-kdb` (module `openbq_kdb`, q scripts under `q/`). The ledger section is "Renamed openbq-kdb" in `docs/v10/live-grid-kdb-port.md`.
  - The compose service is `openbq-kdb`, using `${KDB_IMAGE}`, whose default is the maintainer's private, digest-pinned, linux/amd64-only image; others build theirs with `compose.kdb-build.yml`. It runs the repository's `q/startup.q` and `q/persist.q` read-only from `/opt/openbq-kdb`, keeps its tick logs on the `kdb-data` volume, and recovers from a crash by replaying the logs of today and the two days before. A torn log tail (host crash, `ENOSPC`) is cut back to its last whole chunk, and one bad log cannot switch logging off (checked on a real q by `q/tests/test_persist.py`).
- **The `live` compose profile.** `openbq-kdb` and `live-grid` are opt-in and have no host port. `openbq-kdb` and the S3 tier (`rustfs`, `rustfs-init`, `eod-dump`) sit on `live-private` only, an `internal: true` network that `live-grid` also joins; `live-grid` keeps `openbq-internal` for the API and the gateway, so funnel-gateway and openbq-api cannot reach q or RustFS. The default stack is still `openbq-api` plus `tailscale`. The kdb licence comes from `KDB_LICENSE_DIR` (default `./kdb-license`) and is mounted read-only. `compose.kdb-build.yml` builds kdb-x locally.
- **The S3 tier on RustFS 1.0.1** (user ruling: RustFS, not MinIO). It covers bucket init (`scripts/s3_init.py`), `eod-dump` (`scripts/eod_dump.py`) and the lake read-back in a separate `openbq-lake` image (`Dockerfile.lake`, with `openbb-deltalake`). The env files `rustfs.env` and `eod.env` are optional, and the tier fails closed without them. RustFS data is kept on the host (`${RUSTFS_DATA_DIR:-./rustfs-data}`).
- **funnel-gateway 10.0.0.** It adds the `/grid` family behind the `liveGrid` setting, which is off by default, so `/grid` answers 503. That family is Bearer-gated, metered per symbol, capped at 60 frames per socket and admitted with a single-use ticket. It also serves live-grid's Subscriptions page and watchlist API (V10-P5). `funnel-gateway/policy.mjs` gains the `/grid` rules and the grid frame rule. BDOBB 10.0.0 vendors it.
- **BDOBB examples** are synced with `EPISODE=10`. The live-grid example goes to `live-grid/apps.json`.
- **Unchanged from v9.0.0:** `ts-config/`, `Dockerfile.v3`, `rss-ticker-config/` and the ports: 443 for ODP, 8443 for the Episode 3 reference, 8088 for rss-ticker and 10000 for the gateway (Funnel). `docker-compose.v3.yml` changes only its three image tags, 9.0.0 to 10.0.0 (`openbq-local`, `openbq-episode3-demo`, `openbq-key-maint`).

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
- `docker build -f Dockerfile.v3`;
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
