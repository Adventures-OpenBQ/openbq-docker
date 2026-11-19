<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Episode 2 Workspace companion — historical browser checkpoint

Optional source-built official Workspace/Lite. Episode 1 and the direct Episode 1 → Episode 3 route do not require this service.

Clone the official monorepo and checkout the exact commit in `source.json`, then from the backend repository root:

```sh
workspace/scripts/assemble.sh /path/to/workspace-checkout
cd workspace/build-context
patch -p1 < ../patches/001-pinned-build-and-bun.patch
patch -p1 < ../patches/002-local-state-exclusions.patch
patch -p1 < ../patches/003-runtime-healthcheck.patch
patch -p1 < ../patches/004-frozen-backend-build.patch
```

The patches pin base images and build tools and use the published Bun frontend lock. Assembly verifies and copies the recorded resolved backend lock; the Docker build checks that lock and refuses dependency re-resolution. Build frontend first, then runtime, to avoid overlapping memory-heavy build stages. Source and build context are not a deployment success claim. See the series Episode 2 rehearsal report for measured results.

Build the frontend and runtime images using the complete commands in [REPRODUCE.md](../REPRODUCE.md#original-workspace-source-build) before starting Compose; the service uses a local image and does not build it automatically.

Run it from the repository root with `docker compose --profile workspace up -d`; without the profile only the ODP backend starts. Accounts, dashboards, application secrets and Redis state live in this service's `/data` volume (`openbq-episode2_workspace-data`, the name the former standalone `workspace/compose.yaml` project used, so existing accounts carry over). They are separate from ODP settings and from BDOBB. Do not commit state or generated startup credentials; the upstream entrypoint prints a password into logs.

Privacy gates are installed with `git config core.hooksPath .githooks` from the repository root. Keep actual node domains, IDs, credential files and raw runtime logs in ignored `local-rehearsal/` records; publish placeholder-based instructions only.

The preserved image rendered the login screen, accepted local login, and discovered the backend catalogue in the browser. See [REPRODUCE.md](../REPRODUCE.md) for the original image and remaining dashboard persistence qualification.
