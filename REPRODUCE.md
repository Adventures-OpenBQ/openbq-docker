# Reproduce the v1 backend from source

Copyright 2026 SecretoftheUniverse.com LLC. Licensed under Apache-2.0; retain upstream licenses and notices.

The v1 tag provides a pinned Docker source-build recipe for the backend. Its Python dependencies and base image are pinned, and reviewed provider overlays are checked against their exact original package files during the build. Docker Compose uses a locally built backend image and a pinned Tailscale sidecar.

The dependency install also checks the pinned user-agent corpus against
`security/public-user-agent-policy.json` and removes exactly two reviewed
records containing a private-network URI or unexplained authentication
assignments. This happens in the install layer before it is committed; the
original records are not retained in a deleted-file layer. The other 326,131
records remain byte-for-byte intact. A changed corpus or unexpected filtered
result stops the build. The sanitizer reports only counts and digests.

The public repository is [Adventures-OpenBQ/openbq-docker](https://github.com/Adventures-OpenBQ/openbq-docker). Downloadable files, when provided, are listed on the [v1 release page](https://github.com/Adventures-OpenBQ/openbq-docker/releases/tag/v1.0.0). These instructions build from source and require no prebuilt backend image archive. Check a release source archive against its accompanying `SHA256SUMS` and source manifest; the manifest identifies its exact Git commit.

## Create a separate reader installation

Use Docker with Compose V2 and Buildx. Create a dedicated checkout and a new Tailscale node:

```sh
git clone --branch v1.0.0 https://github.com/Adventures-OpenBQ/openbq-docker.git openbq-reader-v1
cd openbq-reader-v1
git rev-parse HEAD
cp ts.env.example ts.env
```

Follow [README.md](README.md) to configure your own `ts.env` and Serve hostname. Keep registered provider credentials, existing Tailscale identity state and existing OpenBB volumes out of this installation. The tracked `credentials.demo.env` contains only the providers' intentionally public EIA and Congress.gov demonstration tokens. The reader Compose override selects that file directly.

## Build for your Docker host

Choose the command matching the Docker host architecture. Both commands use the same Dockerfile and dependency lock.

For an x86-64 Linux Docker host:

```sh
docker buildx build --platform linux/amd64 --load -t openbq-local:1.0.0-reader .
```

For an ARM64 Linux Docker host:

```sh
docker buildx build --platform linux/arm64 --load -t openbq-local:1.0.0-reader .
```

Docker Desktop can build either target when its emulation is configured. Native builds are appropriate for the corresponding host architecture. The release receipt records the exact tested image IDs and platforms; another architecture's result does not replace its qualification.

Start the dedicated reader project with the newly built image:

```sh
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml config --quiet
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml up -d --no-build
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml ps
```

Settings and user data are stored in this project's named volumes. Tailscale identity state is created locally for the dedicated node. Source archives contain neither runtime volumes nor private credentials.

## Verify the installation

Follow [DEMO-VERIFY.md](DEMO-VERIFY.md) for keyless/public-demo acceptance. From another authorized tailnet device, run the documented smoke and isolation checks against the node's actual HTTPS hostname. A data check requires nonempty results with the expected content. Provider limits and public-demo quotas can constrain a live check; a registered-key result does not replace the reader pass.

The historical NAS measurements in [VERIFICATION.md](VERIFICATION.md) describe the original rehearsal. Current qualification is tied to the release's source and image receipts, rather than the original NAS image ID or an old source checkpoint.
