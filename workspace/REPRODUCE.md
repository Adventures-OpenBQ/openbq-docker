# Reuse or build the optional Workspace companion

Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0; retain upstream notices.

V3 retains the optional Episode 2 Workspace component independently of BDOBB
and the reference backend. The default Compose profile selects the qualified
Linux AMD64 image by immutable digest. Its original image-build source is
`c6a4112a1e931967d35b632f1d6886881f32e824`; it is not relabeled as a V3 build.
ARM hosts run this companion through AMD64 emulation.

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

Build the frontend stage before the runtime to avoid overlapping memory-heavy builds. The frontend build permits an 8 GB Node heap; provision adequate Docker memory. On ARM hosts, this original Workspace AMD64 path uses emulation. Use the local-image override below when running your own source build.

Assembly requires the exact clean upstream commit and extracts its tracked
contents with `git archive`. Ignored operator files and hidden working-copy
overrides are excluded. It verifies the recorded resolved backend lock and
automatically applies security patch 005 and test-fixture packaging patch 006
before making the new context available; do not apply those again. Apply
packaging patches 001–004 as above.
The source checkout and any existing build context are preserved.

The release also records an immutable cache of the qualified AMD64 Workspace
image. To reuse that image instead of compiling it locally:

```sh
docker pull --platform linux/amd64 ghcr.io/adventures-openbq/openbq-docker@sha256:218f6c7098c43abd929ad7d511065ad4e48cade8ed221e13aa46c931a7f53443
```

Image reuse and regression state are independent: repeat qualification in a
new container with an empty NoCopy data volume. The release's registry and
Workspace binding reports identify the original image-build revision; a later
recipe metadata update does not relabel that image.

The Docker build pins Poetry/Cython/setuptools, checks that lock and refuses
to re-resolve dependencies. Frontend installation keeps the original Bun lock
and integrity checks, with bounded download concurrency. A checksum failure
must be investigated rather than bypassed. Run the Workspace source and
compiled-runtime boundary checks described in `workspace/README.md` alongside
the normal login, persistence and data checks.

Copy the Workspace runtime and Tailscale example files as shown in README.md. Assign its actual HTTPS origin to FRONTENDURL/PROURL and that origin plus `/api` to SELFURL. Use its own new Tailscale identity and state directory. Start the optional profile only after configuration.


## Start the V3 companion

Copy and edit the runtime and dedicated sidecar examples:

```sh
cp workspace/runtime.env.example workspace/runtime.env
cp workspace/ts.env.example workspace/ts.env
```

Set `FRONTENDURL` and `PROURL` to the companion's own HTTPS origin, and
`SELFURL` to that origin plus `/api`. Supply your own Tailscale provisioning
credential in its ignored environment file. Keep the companion node and state
separate from the SDK node. Then include the V3 overlay:

```sh
docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile workspace up -d
```

To use your own source build instead of the qualified registry cache:

```sh
OPENBQ_WORKSPACE_IMAGE=openbq-workspace-local:2.0.0 \
  docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile workspace up -d
```

Image reuse does not reuse regression state. For qualification, replace the
Workspace data mount with a new NoCopy volume and use a separate sidecar
identity/state. The normal profile preserves the existing Episode 2 migration
volume; changing the Compose project name alone does not isolate that volume.
An explicit regression override can contain:

```yaml
services:
  workspace:
    volumes: !override
      - type: volume
        source: workspace-data
        target: /data
        volume: {nocopy: true}
volumes:
  workspace-data:
    name: ${WORKSPACE_REGRESSION_VOLUME:?Set an unused regression volume name}
```

Verify that the chosen volume does not exist before starting the regression.
Keep the original Workspace data volume and ordinary sidecar state intact.
Reader/demo data, registered-key SDK data, Workspace ownership/logging/proxy
boundaries, and BDOBB full-reference rendering are separate qualification
checks. The inherited image's existing checksum, installed package inventory,
full-layer privacy and restore receipts remain bound to its original identity.
