<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v9.0.0 release receipt (2026-10-14)

Gated tree: `d66e4d0` (`claude/openbq-docker-v9`). This receipt commit changes only this file. `release/v9` contains `release/v8` = v8.0.0 `ebd3b85`, through merge `e393e13`. User order: "yes, cut openbq-docker v9 and tag v9.0.0".

## What v9.0.0 adds over v8.0.0

- **The EODHD provider extension, openbq-eodhd 9.0.1** (Episode 9; 9.0.0 at the 2026-10-14 cut, see *Re-cut*). It is vendored in `v9/eodhd/source/` from Adventures-OpenBQ/openbq-eodhd at `59603cc`, tag `v9.0.1`, and is byte-identical to `git archive v9.0.1`; `v9/eodhd/source.json` names both. 9.0.1 is 9.0.0 (`7f4cbe2`, the release on PyPI) plus the v9 review fixes, merged upstream in openbq-eodhd #2: the key is redacted from errors, quota and upstream failures are mapped, the dividend yield uses a split-only basis, and calendar paging handles single days. The EODHD SDK is vendored inside the package, so the images no longer fetch it or pin its extra dependencies.
  - The package is bdobb-dev/openbb-docker's `openbb-eodhd` v9.6.3, with fixes through v9.6.6, renamed `openbq-eodhd` (module `openbq_eodhd`). The ledger is `docs/v9/eodhd-port.md`.
  - The OpenBB contract is unchanged from the donor: provider `eodhd`, `obb.eodhd.*` on `/api/v1/eodhd`, and widget ids `eodhd_*_eodhd_obb`.
  - The image installs it (`Dockerfile.v3`) and runs `v9/eodhd/verify.py` at build time.
  - `credentials.env.example` gains `EODHD_API_KEY=`, with no value.
- **BDOBB examples** are synced with `EPISODE=9`. They add *Example Dashboard - Version 9.0.0 - Calendars*, which needs `EODHD_API_KEY`.
- **Unchanged from v8.0.0:** `ts-config/`, both compose files, `funnel-gateway/` and `rss-ticker-config/`. Ports stay as before: 443 is ODP (tailnet), 8443 the Episode 3 reference (tailnet), 8088 rss-ticker (tailnet) and 10000 the gateway (Funnel). `funnel-gateway/policy.mjs` is unchanged.

## Gates (all passed)

| # | Gate | Result |
|---|---|---|
| 1 | `scripts/check-public.py --history HEAD` | PASS, including reachable history |
| 2 | House copyright headers | no file new in v9 is missing one (the headerless `Dockerfile.v3`, `README.md` and binary fixtures are as at v8.0.0) |
| 3–6 | `docker compose config`: default; `web` + `workspace`; with `docker-compose.v3.yml`; v3 overlay + `web` | valid |
| 7 | `workspace/tests` (unittest) | 12 OK |
| 8 | `v3/tests` (pytest in `python:3.12`; starlette 1.7.0, httpx 0.28.1, anyio 4.15.1) | 68 passed |
| 9 | `tests` (pytest in `python:3.12`; web profile, compose, all four Serve configs) | 11 passed, 5 subtests |
| 10 | `funnel-gateway` `npm ci && npm test` (`node:22`) | pass, 0 fail |
| 11 | `docker build -f Dockerfile.v3` (runs `v9/eodhd/verify.py`) | built |
| 12 | `lanes/tests` in the built image | 22 OK |
| 13 | `provider-fixes/tests` (`scripts/test-provider-fixes.sh`) | 42 OK |
| 14 | `examples/episode3` assembly and server tests in the image | 3 OK; OK |
| 15 | `v9/eodhd/tests` in the built image (no EODHD call) | 9 OK |
| 16 | `verify-settings.py` on a local key-mode container (127.0.0.1, throwaway credential) | 8 checks passed |
| 17 | `verify-dashboards.py`, same container | 21 checks passed |
| 18 | `verify-v4-routes.py`, same container | PASS |
| 19 | `/apps.json` with an `Origin` header after a no-Origin fetch | 48 apps including EODHD, `access-control-allow-origin: *` |

## Known, carried from v8.0.0

The served examples keep `img` empty: the image does not serve `/openbq/bdobb-logo.svg`, which BDOBB's current `apps:sync` writes. *V4 core tools* is the older single-probe *Date expressions* tab; BDOBB v7.0.0 and later ship six probes and a note. Both need a later stack change.

No image was published and nothing was deployed.

## Re-cut (2026-10-16)

The regression walk re-cut v9.0.0 after the v9 review. The review's EODHD fixes went upstream first, in openbq-eodhd #2, and shipped as openbq-eodhd 9.0.1 (`59603cc`). 9.0.0 (`7f4cbe2`) was already on PyPI and can't be replaced. This tree vendors 9.0.1 (`99a3f95`), with the SDK inside the package, so `v9/eodhd/requirements.extra.lock` is gone. `verify.py` also refuses a separately installed `eodhd` (`de99d73`, from review M2).

Gates on `de99d73`:
- `scripts/check-public.py --history HEAD`: PASS.
- `tests`: 33 passed.
- `docker build` of both API Dockerfiles: built, `pip check` clean, and `verify.py` PASS for openbq-eodhd 9.0.1, amd64 and arm64.
- The NAS ran the image with `nas-verify` (smoke, app layouts, CFTC, heavy routes, isolation, provider fixes, v4 routes): all passed.
- Live EODHD calls with the demo token: prices and dividends returned 200. A refused symbol returned 502 with no key and no `api_token` in the body.
- The BDOBB client regression passed: OBBject warnings, E05-047, 9 fixtures, the apps walk (46 non-BLS and 5 BLS apps), and the smoke nine. The smoke nine needed a rerun: its first run hit one transient yfinance profile failure, and the route then answered 200 three times in a row.

GHCR `9.0.0`, built for amd64 and arm64:
- `openbq-local` `sha256:84ef1e13fece055b798057b14a02a6a12ab831370250650f1cd797bdb975ca29`, image revision `de99d73`.
- `openbq-table-service` `sha256:f80413f2c049867ae5d93fccf0073a6d3714cf033fdd34dfa47b9c75acf83774`, from BDOBB `8e7fca1` per `table-service/source.lock.json`, unchanged.
- `openbq-key-maint` `sha256:ba2d3d252680be8c5c804296f29aea2ebde935ad1294dce65df56295728445b5`, the 8.0.0 image re-tagged, unchanged.

The funnel gateway stays at 8.0.0. `latest` was not moved.
