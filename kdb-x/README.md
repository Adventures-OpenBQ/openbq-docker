<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# kdb-x — KDB-X as a container, for any platform

**This directory ships no KX software.** It is a recipe. The build downloads
KDB-X from KX's own distribution portal, so you obtain it directly from KX
under your own acceptance of their terms — nothing here redistributes a kdb+
binary, which the licence does not permit.

The licence is not baked in either. Mount your own at runtime.

## Build

Single platform, straight into your local daemon:

```bash
docker build --build-arg KX_VERSION=<exact-version> -t openbq-kdb-local:10.0.0 kdb-x/
```

Real multi-arch (buildx cannot `--load` two platforms, hence `--push`):

```bash
docker buildx build --build-arg KX_VERSION=<exact-version> --platform linux/amd64,linux/arm64 \
  -t ghcr.io/<you>/kdb-x:1.1 --push kdb-x/
docker buildx imagetools inspect ghcr.io/<you>/kdb-x:1.1   # verify BOTH are there
```

That last check matters. A single-arch tag still resolves on the platform it
happens to match, so a broken manifest looks healthy until an amd64 host
silently pulls AArch64 binaries — `docker pull` and `COPY` never execute
anything, so the failure surfaces only when something tries to spawn q.

The build asserts the architecture itself: it reads the ELF `e_machine` of the
downloaded `q` and fails if it does not match the platform being built.

## Platform names

KX names builds by OS *and* CPU, and the OS half is easy to miss:

| Target | KX prefix | Format |
|---|---|---|
| Linux x86-64 (most servers, NAS) | `l64` | ELF |
| Linux AArch64 (Docker on Apple Silicon) | `l64arm` | ELF |
| macOS Apple Silicon (native, not containers) | `m64` | Mach-O |

A `m64` build will not run in a Linux container at all. If you ran KX's
installer on a Mac it gave you `m64` — useful for running `q` in a terminal,
not for this.

## Run

```bash
docker run -d --name kdb \
  -v "$PWD/../kdb-license:/licence:ro" -e QLIC=/licence \
  -p 127.0.0.1:5000:5000 openbq-kdb-local:10.0.0
```

`KX_PORT` defaults to `0.0.0.0:5000` — all interfaces, deliberately, because
this image's documented use is exactly the standalone container above: a
loopback bind *inside* the container is unreachable through `-p` at all (the
handshake fails behind docker-proxy, even though `nc -z` on the published port
looks fine), so `127.0.0.1` as the default would make this very command not
work. Exposure is controlled on the **host** side instead, with
`-p 127.0.0.1:5000:5000` as shown above.

**Override this if you run the image differently.** In a stack where this
container shares a network namespace with others (e.g. spawned as a child of
another service, or `network_mode: service:...` in compose), bind loopback
instead:

```bash
-e KX_PORT=127.0.0.1:5000
```

Getting this backwards is a real exposure, not a cosmetic one: `0.0.0.0`
inside a shared namespace publishes an **unauthenticated q — and q IPC
executes arbitrary q code — to every peer that can reach this container**.

## The licence file

KX emails the licence as **base64**; `q` wants it **decoded**:

```bash
base64 -d < licence.b64 > kdb-license/kc.lic
```

If you ran KX's installer, `~/.kx/kc.lic` is already decoded and can be copied
straight across — it is platform-independent, unlike the binary.

## In this stack (the `live` profile)

`docker-compose.yml` runs `openbq-kdb` from `${KDB_IMAGE}`, defaulting to
`openbq-kdb-local:10.0.0`. Build that local image with `compose.kdb-build.yml`
and an explicit exact `KX_VERSION`. No maintainer-private registry is required.
Use the matching architecture for amd64 or arm64; a tag alone does not prove
that a binary runs on either. Keep built KX images local or private.

Set `KX_VERSION=<exact-version>` in the shell; there is no mutable latest default. The stack sets `KX_PORT=5000` (all interfaces of the kdb
container, which sits on the internal bridge with no host port) and passes
`v10/kdb/source/q/startup.q` as q's script, so crash recovery is on either way.

V10 reader assembly uses `openbq-kdb-local:10.0.0` as its default KDB_IMAGE,
with no maintainer registry access. Set KX_VERSION to the exact KX release to
build before running compose.kdb-build.yml; a mutable latest default is not used.
The recipe checks the ELF architecture independently for amd64 and arm64.
Keep built KX images local or private. No KX binary or license is distributed.

After setting the exact `KX_VERSION`, build the service selected by the reader recipe:

```sh
docker compose -f docker-compose.yml -f compose.kdb-build.yml --profile live build openbq-kdb
```
