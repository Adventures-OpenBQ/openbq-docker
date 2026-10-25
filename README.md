# openbq-docker — ODP backend

A headless Open Data Platform backend on Docker, with private HTTPS through a separate Tailscale sidecar. Companion to **Adventures in OpenBQ**. This is an independent packaging recipe for the official OpenBQ-stewarded OpenBB V5 packages, whose names and commands remain `openbb-*`.

## Scope

Official core/API, seventeen providers, news, and technical/quantitative/econometric extensions. No desktop frontend, custom providers, running MCP service, agent, or later storage stack in the ODP service. `requirements.in` declares the intended direct packages; `requirements.lock` records the full resolved environment used by the Docker build.

The original Episode 1 checkpoint remains `v1.0.0`. The v2 candidate applies reviewed BLS/TMX compatibility fixes to the same locked provider packages; the overlay verifies every original file hash before applying changes. See [provider fixes](provider-fixes/README.md) and [verification](VERIFICATION.md).

The optional `workspace/` companion is a separate source-built service in rehearsal; a backend checkpoint does not certify the full Workspace dashboard/recovery workflow.

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
python3 scripts/verify-provider-fixes.py https://openbq.YOUR-TAILNET.ts.net
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

### Heavy routes

CFTC (`/api/v1/cftc/*`) and FINRA bonds run in a second `openbb-api` process, the "heavy" lane (`lanes/openbq_lanes.py`), so their CPU work and 30–160 MB responses cannot stall `/widgets.json` or other routes. One request runs at a time and the rest queue. A request still running after 165 s gets 504 and the lane is restarted; a full queue, or a lane still starting, gets 503 with `Retry-After`; a result over 256 MB gets 413. `/widgets.json` and `/apps.json` are built once per process and then served from memory (restart the API after editing workspace apps or widget settings). `GET /openbq/lanes` shows the lane's pid, memory and restarts (behind the API's Basic auth when that is on, open otherwise). Settings (`credentials.env`): `OPENBQ_ISOLATE` (path prefixes; empty turns the lane off), `OPENBQ_LANE_DEADLINE`, `OPENBQ_LANE_QUEUE_MAX`, `OPENBQ_LANE_RSS_MB` (restart above, default 3584), `OPENBQ_LANE_STARTUP_LIMIT` (replace a worker still starting after this, default 180 s), `OPENBQ_MAX_RESULT_BYTES`. Check them with:

```sh
python3 scripts/verify-heavy-routes.py http://127.0.0.1:6900   # widgets.json keeps answering under load
python3 scripts/verify-lane-contract.py LANE_URL IN_PROCESS_URL  # same answers with OPENBQ_ISOLATE empty
docker run --rm -v "$PWD:/src:ro" -w /src openbq-local:2.0.0 python -m unittest discover -s lanes/tests
```

## Credentials and restart

### Demo keys

`credentials.demo.env` is committed and holds only public demo keys the providers publish
(api.data.gov's `DEMO_KEY` for EIA and Congress.gov), so those cards answer before you have keys of
your own. Compose loads it first and `credentials.env` second, so any key you set wins; keep a
demo-covered line commented out in `credentials.env` (an empty `NAME=` would replace the demo key with
nothing). Demo keys are rate-limited (30 requests an hour, 50 a day per IP). BLS, CFTC and EconDB need
no key. The live check of each value is in [the receipt](docs/credentials-demo-receipt.md);
`tests/test_credentials_demo.py` allows no other names or values in the file.

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

## Public repository checks

Enable the local gates after cloning:

```sh
git config core.hooksPath .githooks
python3 scripts/check-public.py --history
```

Commits scan tracked, staged and unignored files; pushes also scan the history reachable from the pushed refs; CI and a bare `--history` scan every branch and tag. Local deployment evidence and the machine-specific `scripts/scrub-private-patterns.txt` remain ignored. Reports use placeholder hostnames and addresses. The scanner reports filenames and finding categories, never matched values.

Real `credentials.env` files may be used on the NAS, but stay out of Git and Docker build contexts. Example credentials must contain empty values or obvious placeholders; an `.example` suffix does not make a real key safe to publish. The one exception is `credentials.demo.env`, whose public demo values `scripts/check-public.py` allows by exact name and value. Screenshots still need visual review before publication.

## Episode 3 candidate: BDOBB and the reference backend

The optional [v3 Compose overlay](docker-compose.v3.yml) builds two independent
services: ODP with [our original yfinance extension](v3/yfinance/README.md), and
the [OpenBQ reference backend](examples/episode3/README.md). The shared private Tailscale sidecar serves ODP on 443 and the reference
backend on 8443. No NAS host ports or public Funnel are enabled.

The overlay also runs [key-maint](key-maint/README.md), the provider key status
service behind BDOBB's Settings ▸ Provider API Keys. It mounts `credentials.env`
(create it first, as in [Start](#start), or Docker makes a directory of that
name) and `./key-maint-admin`, whose 0700 mode guards the key-value socket;
key-maint sets that mode itself on start.

```sh
cp v3.env.example v3.env
mkdir -p key-maint-admin
# Optional: add your frontend origin to EXTRA_CORS_ORIGINS.
docker compose -f docker-compose.yml -f docker-compose.v3.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.v3.yml build
docker compose -f docker-compose.yml -f docker-compose.v3.yml up -d
```

The reference `/apps.json` advertises 70 self-contained cards with zero missing
widget references. Its `/bundle.apps.json` download adds the keyless ODP market
examples for a 76-card BDOBB file import. No app carries BDOBB layout extensions:
BDOBB v3 refuses them, and the pivot examples arrive with v4. The Episode 3 app
entry carries the BDOBB logo in standard image fields. Workspace is an optional Episode 2
comparison, not a prerequisite for this setup.

Released as `v3.0.0` with BDOBB v3.0.0: `openbq-local:3.0.0` and
`openbq-key-maint:3.0.0`, both built from this checkout, are the images the 2026-10-15 regression ran on a NAS.

The reference recipe carries forward the previously qualified PDF repair from `bdobb-dev/backends-for-openbb` commit `32615f789f9423ea14d3f95003da250f4ef5bcfc`. Sample and Bitcoin PDFs use immutable GitHub raw URLs because the original S3 bucket returns AllAccessDisabled. Downloaded bytes match the pinned upstream fixtures; this changes asset transport, not PDF content.

### Component licenses

The first-party key-maint component is AGPL-3.0-only. Where included, the first-party rss-ticker component is also AGPL-3.0-only. Each component carries its own LICENSE and LICENSING.md; earlier grants and third-party notices are preserved. Other components retain their stated licenses.
