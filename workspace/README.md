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

Assembly reads the exact pinned Git commit, rather than copying the working
directory. Ignored files and local overrides cannot enter the build context.
It verifies the recorded resolved backend lock and automatically applies
`005-workspace-request-boundaries.patch` before exposing the new context. Do
not apply patch 005 a second time. The source checkout and existing context
are preserved; assembly refuses to overwrite a context.

Apply packaging patches 001–004 as shown above. They pin base images and build
tools and use the published Bun frontend lock. The Docker build checks the
backend lock and refuses dependency re-resolution. Build frontend first, then
runtime, to avoid overlapping memory-heavy build stages. Source and build
context are not a deployment success claim. See the series Episode 2
rehearsal report for measured results.

Build the pinned public source with the manual frontend/runtime sequence in [REPRODUCE.md](REPRODUCE.md#original-workspace-source-build) before starting the companion. The V5 profile defaults to `openbq-workspace-local:2.0.0` on Linux AMD64 and uses `pull_policy: never`: Compose neither compiles Workspace nor pulls an image automatically. Ordinary readers need no GHCR credentials. The same guide covers a different local tag, an optional private cache for authorized operators, and fresh NoCopy regression state.

Run it from the repository root with `docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile workspace up -d`; without the profile only the ODP backend starts. Accounts, dashboards, application secrets and Redis state live in this service's `/data` volume (`openbq-episode2_workspace-data`, the name the former standalone `workspace/compose.yaml` project used, so existing accounts carry over). They are separate from ODP settings and from BDOBB. Do not commit state or generated startup credentials; the upstream entrypoint prints a password into logs.

Privacy gates are installed with `git config core.hooksPath .githooks` from the repository root. Keep actual node domains, IDs, credential files and raw runtime logs in ignored `local-rehearsal/` records; publish placeholder-based instructions only.

The historical qualification rendered the login screen, accepted local login, discovered the backend catalogue and checked dashboard persistence. Current image and reader qualification are recorded in the release regression evidence. This legacy client is a measured compatibility checkpoint; full reference-widget support is a separate BDOBB V4 gate.

## Certificate trust-store repair

The recorded backend lock pins `certifi==2026.10.19` with its published artifact
hashes. This incorporates the upstream [emSign trust-store repair](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
without changing any other resolved package, the pinned Workspace source or the
frontend lock. A dependency change requires rebuilding the Workspace runtime;
unchanged SDK images can still be reused by digest.

After building the reader image, verify the actual runtime trust store:

```sh
docker run --rm --network none --entrypoint python \
  -v "$PWD/workspace/runtime-checks:/checks:ro" \
  openbq-workspace-local:2.0.0 /checks/test_certifi_trust.py
```

The check rejects the compromised emSign G3 root, retains valid public roots,
and requires certificate and hostname verification to stay enabled. It does
not replace the login, refusal, persistence or browser-data regression checks.

## Request and file boundaries

Patch 005 checks file-widget ownership before changing stored bytes or rows,
removes the unused MCP forwarding endpoint, and removes raw request
headers/body, validation inputs and storage connection strings from the
affected logs. The existing schema type remains for upstream compatibility;
it does not expose a proxy route.

The source contract checks use the image's dependencies and the assembled
source because the packaged runtime compiles these modules into Cython
binaries:

```sh
docker run --rm --network none --entrypoint python \
  -e WORKSPACE_BACKEND_ROOT=/source/backend \
  -v "$PWD/workspace/build-context:/source:ro" \
  -v "$PWD/workspace/runtime-checks:/checks:ro" \
  openbq-workspace-local:2.0.0 /checks/test_request_boundaries.py
```

These source checks supplement fresh-volume HTTP login, cross-account
refusal, owner deletion, proxy refusal and persistence checks against the
rebuilt runtime. They do not establish compiled-runtime behavior by themselves.

## Public test-fixture packaging

Assembly also applies patch 006 and includes its build-only guard. After
backend compilation, before copying the virtual environment into the runtime
image, it removes only Tornado 6.5.8's unused public HTTPS unittest key at
`tornado/test/test.key`. Exact version, file size and SHA-256 guards reject
unexpected inputs. Other modules and the original distribution RECORD remain
unchanged. The intentional package overlay is recorded separately at
`/opt/.venv/public-test-fixture-removals.json`.

This removes the resource before any final image layer contains it; deleting
it from an already assembled runtime image would leave the earlier layer
intact. The complete saved-image privacy check remains required.
