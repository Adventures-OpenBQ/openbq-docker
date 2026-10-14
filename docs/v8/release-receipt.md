<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v8.0.0 release receipt (2026-10-14)

Gated tree: `d1a7ff9`. This receipt commit adds only this file. `release/v8` contains `release/v7` (`4cad478`, v7.0.0).

## What v8.0.0 adds over v7.0.0

- The `web` compose profile: `funnel-gateway`, ported from openbb-docker v8.0.3 with `/api`, `/state` and `/news` only, and `rss-ticker`. See `funnel-gateway/README.md` and `docs/v8/news-relay-and-hidden-dashboards.md`.
- BDOBB's hidden docks dashboard is served on its reserved id, including from Workspace/Lite. A docks `DELETE` is checked against the client's revision.
- The BDOBB examples are synced from the v8 freeze `de951a1`. The 5-year TIPS maturity is dropped from the v8 FRED overlay.
- **rss-ticker uses `ghcr.io/artcashin/rss-feedhandler:8.0.1`**, digest `sha256:bbe5e391249176d91490b570d4defeb934d1ddf8d56dcbee8c423bed2c3ea49c`.
  - 8.0.1 is the newest published image. Tags v8.1.0–v8.3.0 exist only in the source repo, with no image.
  - 8.0.1 is built for amd64 and arm64; 8.0.0 was amd64 only.
  - It changes no application code from 8.0.0.
  - It started healthy (`{"status":"ok","version":"8.0.1"}`) on `rss-ticker-config/config.yaml.example`.
  - The GHCR package is private, so pulling it needs a login with access to `artcashin/rss-feedhandler`.
- **Serve/Funnel brought up to date with openbb-docker v10.1.8:**
  - `ts-config/serve.json` publishes the same ports as `serve-funnel.json` except the gateway's `:8443`, so rss-ticker is on tailnet `:8088` in both. It carries no `AllowFunnel` at all.
  - The Funnel swap is written to `serve.json.new`, checked with `jq empty` and moved over.
  - Tailscale Services (`svc:`) were not ported: their hostnames must be literal tailnet names and need admin-side setup.
  - The `YOUR-TAILNET` placeholders are kept, and no tailnet name or address is committed.

## Gates (all passed)

| # | Gate | Result |
|---|---|---|
| 1 | `scripts/check-public.py --history HEAD` | PASS, including reachable history |
| 2 | House copyright headers on repo-authored files | 0 missing |
| 3–5 | `docker compose config`: default; `web` + `workspace` profiles; with `docker-compose.v3.yml` | valid |
| 6 | `workspace/tests` (unittest) | OK |
| 7 | `v3/tests` (pytest; starlette 1.7.0, httpx 0.28.1, anyio 4.15.1) | 68 passed |
| 8 | `tests` (pytest; web profile, compose and Serve configs) | 10 passed, 5 subtests |
| 9 | `funnel-gateway` `npm ci && npm test` (Node 22) | 47 pass, 0 fail |
| 10 | `docker build -f Dockerfile.v3` | built |
| 11 | `lanes/tests` in the built image | OK |
| 12 | `provider-fixes/tests` in the built image | OK |
| 13 | `examples/episode3` assembly test | OK |
| 14 | `verify-settings.py` on a local key-mode container (localhost, throwaway credential) | 8 checks passed |
| 15 | `verify-dashboards.py`, same container | 21 checks passed |
| 16 | `verify-v4-routes.py`, same container | PASS |
| 17 | `/apps.json` from a browser origin after a no-Origin fetch | 46 apps, `access-control-allow-origin: *` |

These are the CI workflow's steps plus the image-level gates. Gates 8 and 9 were run in `python:3.12` and `node:22` with the whole repo mounted: the tests call `git` and `openssl` and read `docker-compose.yml`.

Not done for this tag: no GHCR `openbq-local:8.0.0` image was built, and nothing was deployed.
