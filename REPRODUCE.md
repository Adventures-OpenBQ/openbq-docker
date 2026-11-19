# Build the Episode 2 environment from public source

Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0; retain upstream licenses and notices.

Use the public source-build recipe. No private-registry credentials or historical NAS image archive are required. If using the release source archive, verify its SHA256SUMS before extracting. The attached manifest identifies the exact source commit.

```sh
git clone --branch v2.0.0 https://github.com/Adventures-OpenBQ/openbq-docker.git openbq-v2
cd openbq-v2
```

Follow README.md for the dedicated backend node and optional registered credentials, or DEMO-VERIFY.md for a fresh public-demo/keyless rehearsal. Docker must support the Compose override syntax used by the reader file. Do not use an existing user's volumes or copy an existing node's identity state for a fresh rehearsal.

## Backend builds

```sh
docker build --platform linux/amd64 -t openbq-local:2.0.0 .
# On a native ARM64 target, use --platform linux/arm64 instead.
docker compose up -d
```

The image applies the provider overlay only after checking package versions and original file hashes. A guard mismatch is a build failure, not a reason to remove the guard. The reader override uses the `2.0.0-reader` image tag and public demo environment directly; see its complete build/start commands.

## Original Workspace source build

```sh
git clone https://github.com/OpenBB-finance/workspace.git ../workspace-source-v2
git -C ../workspace-source-v2 checkout be00e95019a55d57af146919ee46b7e1a4859226
workspace/scripts/assemble.sh ../workspace-source-v2
cd workspace/build-context
patch -p1 < ../patches/001-pinned-build-and-bun.patch
patch -p1 < ../patches/002-local-state-exclusions.patch
patch -p1 < ../patches/003-runtime-healthcheck.patch
patch -p1 < ../patches/004-frozen-backend-build.patch
cd ../..
docker build --platform linux/amd64 --target frontend-build -t openbq-workspace-frontend:2.0.0 workspace/build-context
docker build --platform linux/amd64 -t openbq-workspace-local:2.0.0 workspace/build-context
```

Build the frontend stage before the runtime to avoid overlapping memory-heavy builds. The frontend build permits an 8 GB Node heap; provision adequate Docker memory. On ARM hosts, this original Workspace AMD64 path uses emulation. For reader rehearsal, use the `2.0.0-reader` Workspace image tags specified in DEMO-VERIFY.md.

Assembly requires the exact clean upstream commit. It verifies the recorded resolved backend lock and copies it into the new build context, preserving the source checkout. The Docker build pins Poetry/Cython/setuptools, checks that lock and refuses to re-resolve dependencies. Frontend installation keeps the original Bun lock and integrity checks, with bounded download concurrency. A checksum failure must be investigated rather than bypassed.

Copy the Workspace runtime and Tailscale example files as shown in README.md. Assign its actual HTTPS origin to FRONTENDURL/PROURL and that origin plus `/api` to SELFURL. Use its own new Tailscale identity and state directory. Start the optional profile only after configuration.

## Qualification scope

Confirm backend data access through its sidecar separately from Workspace login, catalogue acceptance, rendering, persistence and backup/restore. A successful data API, connection count or application shell is not a full widget-rendering pass. Keep keyless/public-demo and registered-key receipts distinct; source-equivalent public proof may carry forward only with an explicit earlier receipt and successful current keyed testing.

The original Workspace snapshot excludes optional proprietary TradingView assets; their functionality cannot be certified merely by building the public source. FINOS and BDOBB comparisons have separate source pins and browser receipts. Use current release evidence for what was actually exercised.

Historical records may cite original image04222ea5 and earlier927/926-widget catalogues. Those describe their dated rehearsals, not new results for this assembly. Source pins alone do not make image bytes reproducible: OS packages and upstream font downloads remain external build inputs. No personal account database, credentials or Tailscale identity is included.
