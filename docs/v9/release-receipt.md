<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v9.0.0 release receipt (2026-10-14)

Gated tree: `d66e4d0` (`claude/openbq-docker-v9`). This receipt commit changes only this file. `release/v9` contains `release/v8` = v8.0.0 `ebd3b85`, through merge `e393e13`. User order: "yes, cut openbq-docker v9 and tag v9.0.0".

## What v9.0.0 adds over v8.0.0

- **The EODHD provider extension, openbq-eodhd 9.0.0** (Episode 9). It is vendored in `v9/eodhd/source/` from Adventures-OpenBQ/openbq-eodhd at `8da2435`. `v9/eodhd/source/` is byte-identical to `git archive 8da2435`. `v9/eodhd/source.json` names that commit and the tag `v9.0.0`.
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
