<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-docker v8.0.0 release receipt (2026-10-14)

Gated tree: `2a4d087`. This receipt commit changes only this file. `release/v8` contains `release/v7` (`0147e7f`: v7.0.0 `4cad478` plus the 5-year TIPS maturity drop, carried from v2 on 2026-10-12).

## What v8.0.0 adds over v7.0.0

- The `web` compose profile: `funnel-gateway`, ported from openbb-docker v8.0.3 with `/api`, `/state` and `/news` only, and `rss-ticker`. See `funnel-gateway/README.md` and `docs/v8/news-relay-and-hidden-dashboards.md`.
- BDOBB's hidden docks dashboard is served on its reserved id, including from Workspace/Lite. A docks `DELETE` is checked against the client's revision.
- The BDOBB examples are synced from the v8 freeze `de951a1`. The 5-year TIPS maturity is dropped from the v8 FRED overlay.
- **rss-ticker uses `ghcr.io/adventures-openbq/openbq-rss-ticker:8.0.0`**, digest `sha256:e47d0912b0e21aa2b0fa1ed8898fbabf22e19d65234222d13c83efe54bc11b15`.
  - It is built from `rss-ticker/`, the rss-feedhandler v8.0.1 source (`96dbe26`, MIT) vendored into this repo, for amd64 and arm64.
  - It replaces `ghcr.io/artcashin/rss-feedhandler:8.0.1` (`sha256:bbe5e391…`), which was built from the same commit in a personal namespace (re-cut 2026-10-16).
  - The application reports `"version":"8.0.1"`, its upstream version. It started healthy on `rss-ticker-config/config.yaml.example`.
  - Compose builds it from `rss-ticker/` (`docker compose --profile web build rss-ticker`), so no registry login is needed. The GHCR package is private, like the org's other images, and only the maintainer's NAS pulls it with the org read token.
- **Serve/Funnel: the door is on Funnel port 10000**, so the episode 3 reference keeps 8443 and both run on one node (user ruling, option B). Funnel offers only 443, 8443 and 10000, and 443 stays ODP's. One sidecar applies exactly one serve file; each tailnet file has a Funnel variant that adds only the door:

  | Serve file | Applied by | 443 | 8443 | 8088 | 10000 |
  |---|---|---|---|---|---|
  | `serve.json` | default compose | ODP (tailnet) | — | rss-ticker (tailnet) | — |
  | `serve-funnel.json` | copied over `serve.json` | ODP (tailnet) | — | rss-ticker (tailnet) | gateway (Funnel) |
  | `serve-v3.json` | the v3 overlay (`docker-compose.v3.yml`) | ODP (tailnet) | reference (tailnet) | rss-ticker (tailnet) | — |
  | `serve-v3-funnel.json` (new) | copied over `serve-v3.json` | ODP (tailnet) | reference (tailnet) | rss-ticker (tailnet) | gateway (Funnel) |

  - To swap, run on the deployment host: `cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json`. With the v3 overlay, use `serve-v3-funnel.json` → `serve-v3.json` instead. The sidecar live-applies the file, and a malformed one would kill it.
  - Tailnet-only files carry no `AllowFunnel` at all, as in openbb-docker v10.1.8.
  - `funnel-gateway/config.mjs` accepts an origin on `:10000` and refuses `:8443`. `funnel-gateway/policy.mjs`, the route contract, is unchanged from `8ac084b`.
  - Tailscale Services (`svc:`) were not ported: their hostnames must be literal tailnet names and need admin-side setup.
  - The `YOUR-TAILNET` placeholders are kept, and no tailnet name or address is committed.

## Gates (all passed)

| # | Gate | Result |
|---|---|---|
| 1 | `scripts/check-public.py --history HEAD` | PASS, including reachable history |
| 2 | House copyright headers on repo-authored files | 0 missing |
| 3–5b | `docker compose config`: default; `web` + `workspace` profiles; with `docker-compose.v3.yml`; v3 overlay + `web` | valid |
| 6 | `workspace/tests` (unittest) | OK |
| 7 | `v3/tests` (pytest; starlette 1.7.0, httpx 0.28.1, anyio 4.15.1) | 68 passed |
| 8 | `tests` (pytest; web profile, compose and all four Serve configs) | 11 passed, 5 subtests |
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

## Image

`ghcr.io/adventures-openbq/openbq-local:8.0.0` = `latest` = `sha256:5cb1bcc311cab236f719fdd7f5ccce56a63b2eb437cecb9c515d69f01047f4cc`. It is built for amd64 and arm64 from `Dockerfile.v3` at `d507ff5`. Later v8.0.0 commits change only docs, which the image does not copy. On the pulled image, in key mode: `verify-settings.py` 8 checks, `verify-dashboards.py` 21 checks, and `/apps.json` 200 after a no-Origin fetch, then `access-control-allow-origin: *` with 46 apps.

Nothing was deployed.

## Re-cut (2026-10-16)

The regression walk re-cut v8.0.0 after the v8 review. Its fixes:
- the system dashboard PUT now compares revisions after a lost insert race (`9b8a220`, `eb29232`);
- the pinned example's wording is synced (`41c1dc2`).

GHCR `8.0.0`, all built for amd64 and arm64 from this tree, with image revision `eb29232`:
- `openbq-local` `sha256:71d2a39888f56858b60487e641998ec877bfe4b9cd9efc3d294972ef4a951940`
- `openbq-funnel-gateway` `sha256:f19a72ed5d70aea4aa177f9f746738f81dbafe86b75983aac159e0e1ee127cfa`
- `openbq-table-service` `sha256:a2cd81d3d404699e88b511c637eeb2cd1b6d37afa8bf163c274ccc19f77f88d2`, from BDOBB `727c47e` per `table-service/source.lock.json`
- `openbq-key-maint` `sha256:ba2d3d252680be8c5c804296f29aea2ebde935ad1294dce65df56295728445b5`, unchanged

`latest` was not moved and still names the 2026-10-14 `openbq-local` above.

## Re-cut 2026-10-18: Live TV

- `rss-ticker/` is re-vendored from rss-feedhandler v8.3.1 (`7e3014a`, MIT): the upstream 8.0.1→8.3.1 diff applied on top of this repo's local changes, which stay (subscribed-only delivery, idle feeds kept by the sweep, the 16 KiB favicon cap, and the fetch SSRF guard that 8.3.1 also carries).
- New: an optional `live_tv` channel list. With channels listed, `/widgets.json` publishes one "Live TV" `youtube` widget (`/api/live/video`, Channel picker from `/api/live/channels`) and `/yt` serves a wrapper page. `rss-ticker-config/config.yaml.example` ships the list commented out, so Live TV is off until a reader adds channels.
- Same service, same tailnet port 8088; nothing new is funneled. The public door still relays only `/news` from rss-ticker.
- The image keeps its name, `openbq-rss-ticker:8.0.0`, built locally from source. The application reports `"version":"8.3.1"`.
