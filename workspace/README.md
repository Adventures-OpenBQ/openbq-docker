<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Official Workspace companion

This optional service builds the official pinned Workspace/Lite source. Episode 1 and the direct Episode 1 → Episode 3 route do not require it. Accounts and settings remain separate from the ODP and BDOBB.

Check out the exact official commit recorded in `source.json`. From this repository root, assemble a new disposable context, then apply the reviewed patches in order:

```sh
workspace/scripts/assemble.sh /path/to/clean-pinned-workspace-checkout
workspace/scripts/apply-patches.sh
# Build these stages sequentially to limit peak build memory.
docker build --platform linux/amd64 --target frontend-build -t workspace-frontend:local workspace/build-context
docker build --platform linux/amd64 -t workspace-patched:local workspace/build-context
```

Assembly only copies the clean source and records its relative-file checksums. `apply-patches.sh` checks the complete source record, exact upstream pin and original locks, applies patches001–005, copies the previously recorded resolved lock and packages the reviewed migration tool/manifest. It rejects modified inputs, partial/repeated patch state and dependency drift. Start again from a new assembly after a failed application.

The ordered patch set is:

- `001-pinned-build-and-bun.patch`: recorded base images and the published Bun lock.
- `002-local-state-exclusions.patch`: exclude local state from the build context.
- `003-runtime-healthcheck.patch`: the actual local health route.
- `004-system-dashboard.patch`: the account-scoped hidden docks dashboard at `/pro/dash/sync/system/docks` and schema head `9b1d0c5e7a42`.
- `005-postgresql-settings.patch`: bounded PostgreSQL drivers, explicit migration/bootstrap/serve lifecycle, nonmutating imported startup, exact schema validation and pinned model compatibility. The reviewed full relational transfer tools are packaged alongside it.

Patch004 preserves GET/PUT/DELETE, hidden ordinary listings and its existing revision/conflict behavior. See `docs/v8/news-relay-and-hidden-dashboards.md` for the original docks contract.

For v11 PostgreSQL, follow [the complete migration and restore runbook](postgres/README.md). Use the opt-in `v11/compose.workspace-postgres.yaml` overlay, the separate Workspace database/roles and a private runtime environment. Provision and migrate explicitly, then either import the complete supported SQLite source or explicitly bootstrap a fresh database. PostgreSQL's normal startup only serves a validated existing store. Original keys, Redis and folder storage remain required companions.

The root Compose profile retains the legacy SQLite behavior when no lifecycle selector is supplied. `docker compose --profile workspace up -d` uses the existing `openbq-episode2_workspace-data` volume; that command is not a PostgreSQL migration. Legacy upstream startup can print generated administrator credentials. PostgreSQL and explicitly restored SQLite use the selected lifecycle documented in the runbook.

Run the complete generated-only PostgreSQL gate with `WORKSPACE_TEST_IMAGE=workspace-patched:local workspace/scripts/verify-postgres.sh`. It uses the actual compiled local image, creates private synthetic fixtures, requires every dependency, and qualifies both restore directions after new API writes. No production volume is mounted by the gate.

Privacy hooks are installed with `git config core.hooksPath .githooks`. Keep actual domains, credential files, database snapshots, detailed synthetic evidence and raw runtime logs outside tracked source.
