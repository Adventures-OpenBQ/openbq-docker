> Historical v1.0.0 environment: start with [REPRODUCE.md](REPRODUCE.md) for the archived original images and measured qualification. The development notes below describe the original rehearsal.

# openbq-docker — Episode 1

A headless Open Data Platform backend on Docker, with private HTTPS through a separate Tailscale sidecar. Companion to **Adventures in OpenBQ**. This is an independent packaging recipe for the official OpenBQ-stewarded OpenBB V5 packages, whose names and commands remain `openbb-*`.

## Scope

Official core/API, seventeen providers, news, and technical/quantitative/econometric extensions. No desktop frontend, custom providers, running MCP service, agent, or later storage stack. `requirements.in` declares the intended direct packages; `requirements.lock` records the full resolved environment used by the Docker build.

The verified Episode 1 image is `openbq-local:1.0.0`, built on the NAS from the `v1.0.0` source checkpoint. NAS and second-device rehearsal passed. See [verification](VERIFICATION.md).

## Start

```sh
cp ts.env.example ts.env
cp credentials.env.example credentials.env
chmod 600 ts.env credentials.env
mkdir -p ts-state
# Edit ts.env to supply a dedicated auth key.
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

On QNAP, use `./scripts/nas-docker.sh` in place of `docker` if Docker is missing from the SSH PATH or its default client home is unwritable. Run it from this checkout.

Generate an auth key from [Tailscale's Keys page](https://login.tailscale.com/admin/settings/keys). For this one persistent node, turn Reusable and Ephemeral off; enable Pre-approved if your tailnet requires device approval. Apply existing server tags only if their access policy is appropriate. Enable MagicDNS and HTTPS certificates. Never copy another node's identity state.

Compose project `openbq-stack` keeps its network and settings volume separate from existing stacks. No host ports are published. `openbq-api` listens on its Docker bridge; kernel-mode Tailscale Serve forwards HTTPS port 443. Funnel is disabled. The Docker host and authorized bridge members can reach the API, so this is not isolation from host administrators.

## Test

Read the actual hostname from:

```sh
docker compose exec -T tailscale tailscale status
docker compose exec -T tailscale tailscale serve status
```

From another trusted tailnet device:

```sh
python3 scripts/smoke.py https://openbq.YOUR-TAILNET.ts.net
scripts/verify-isolation.sh openbq.YOUR-TAILNET.ts.net
nc -z -w 5 YOUR-NAS-ADDRESS 6900
```

The first two commands must pass; the last must fail. Check the NAS LAN and tailnet addresses. `smoke.py` validates widget discovery, OpenAPI routes, app/agent catalogues, and a nonempty CBOE quote response. It verifies one data request, not every endpoint.

To diagnose before the sidecar is ready:

```sh
docker compose up -d --no-deps openbq-api
docker compose exec -T openbq-api curl -fsS http://127.0.0.1:6900/widgets.json
docker compose exec -T openbq-api curl -fsS 'http://127.0.0.1:6900/api/v1/cboe/equity/quote?symbol=AAPL&provider=cboe'
```

`ts.env` must still exist, even if it contains an empty key. API-only startup does not prove HTTPS access.

## Credentials and restart

Optional vendor keys go in `credentials.env`, ignored by Git and excluded from the image. Use official variable names; no inline comments after empty values. Recreate the API after editing an environment file. Its settings and OpenBBUserData persist in separate named volumes; Tailscale identity persists in `ts-state/`.

```sh
docker compose up -d --force-recreate
# Recheck identity, catalogue, real data, and isolation.
docker compose stop
# Resume later:
docker compose start
```

Do not remove the volume or identity directory to stop the stack. V5 providers and command paths differ from V4; use this build's `/openapi.json`, not old Yahoo Finance or FMP examples. Provider keys and upstream availability are separate from server health.

Full reader instructions and troubleshooting: [Episode 1](https://github.com/artcashin/adventures-in-openbq-articles/tree/main/articles/01-openbq-on-the-nas).

Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0 for this backend companion; upstream components retain their own licences.
