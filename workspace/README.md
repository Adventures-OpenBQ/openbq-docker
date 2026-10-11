<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Episode 2 Workspace companion — in rehearsal

Optional source-built official Workspace/Lite. Episode 1 and the direct Episode 1 → Episode 3 route do not require this service.

Clone the official monorepo and checkout the exact commit in `source.json`, then from the backend repository root:

```sh
workspace/scripts/assemble.sh /path/to/workspace-checkout
cd workspace/build-context
patch -p1 < ../patches/001-pinned-build-and-bun.patch
patch -p1 < ../patches/002-local-state-exclusions.patch
patch -p1 < ../patches/003-runtime-healthcheck.patch
patch -p1 < ../patches/004-system-dashboard.patch
```

Patch 004 (v8) adds BDOBB's hidden docks dashboard to the backend: `GET`, `PUT` and `DELETE /pro/dash/sync/system/docks`, one per account in a new `system_dashboard` table (Alembic migration `9b1d0c5e7a42`, run by the image's entrypoint), never listed by `/pro/dash/sync/owned` or the app's own sync. It is the same contract as the ODP's key mode; see `docs/v8/news-relay-and-hidden-dashboards.md`. Check a running server with `workspace/scripts/verify-system-dashboard.py https://HOST/api EMAIL PASSWORD`.

Patch 001 pins base images and uses the published Bun dependency lock instead of the absent npm lock. Build frontend first, then runtime, to avoid overlapping memory-heavy build stages. Source and build context are not a deployment success claim. See the series Episode 2 rehearsal report for measured results.

Run it from the repository root with `docker compose --profile workspace up -d`; without the profile only the ODP backend starts. Accounts, dashboards, application secrets and Redis state live in this service's `/data` volume (`openbq-episode2_workspace-data`, the name the former standalone `workspace/compose.yaml` project used, so existing accounts carry over). They are separate from ODP settings and from BDOBB. Do not commit state or generated startup credentials; the upstream entrypoint prints a password into logs.

Privacy gates are installed with `git config core.hooksPath .githooks` from the repository root. Keep actual node domains, IDs, credential files and raw runtime logs in ignored `local-rehearsal/` records; publish placeholder-based instructions only.
