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

On a NAS, use `./scripts/nas-docker.sh` in place of `docker` if Docker is missing from the SSH PATH or its default client home is unwritable. Run it from this checkout.

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

### Large datasets as server-paged tables

The 23 largest table widgets (default response over about 10 MB: FINRA bonds, FFIEC institution structure, the EIA petroleum and gas tables and others) are rewritten in `/widgets.json` to `type: "ssrm_table"` with endpoint `<route>/ssrm`. BDOBB renders them as a paged table, so the full GET never crosses the catalogue caches, the Funnel door or the client. Only `type`, `endpoint` and `ssrm` change; params, columns and names are as before, and a listed id the catalogue lacks is skipped.

`POST <route>/ssrm` answers the OpenBB SSRM request for listed routes only (anything else is 404). The request body is the SSRM JSON; the widget's own params go in the query string. Basic auth is checked first, when it is on, before the cache is read. Params the widget does not declare are dropped before the fetch and the cache key, so they cannot force a fresh download. The first request for a route and params gets the full result once through the API itself, so heavy routes keep their lane, deadline and size cap. The result is cached as a pandas DataFrame (3 GiB LRU by memory, 15-minute TTL); concurrent first requests share one acquisition, at most 2 acquisitions run at once, and one that is not done in 300 s (slot wait included) gets 504 and caches nothing. The reply is `{"rowData", "rowCount"}`: the rows filtered (text contains, case-insensitive; number equals, range, at least, at most) with at most 16 filters, and sorted by at most 3 distinct columns, at most 1,000 per page. When the widget declares `columnsDefs`, every row carries exactly those fields: one absent from the provider's records comes back `null`, and undeclared fields are not served. The last 8 filtered and sorted row orders are kept with each cached result and count against its memory budget, so further pages of the same view are a slice. NaN and infinite numbers come back as `null`; other floats round-trip exactly, and integers stay exact when the column has nulls. A malformed body, more than 16 filters, a sort over 3 columns or naming a column twice, grouping, values, pivot, a combined (`operator`/`conditions`) or unknown filter gets 400; an upstream non-2xx keeps its status and sanitised body. A 200 carries `x-openbq-ssrm: hit` only when both the result and that view's row order came from the cache (no fetch, no new filter or sort), and `miss` otherwise.

The list is committed data, `lanes/ssrm_widgets.json`:

| Widget id | Route |
|---|---|
| `bls_jolts_revisions_bls_obb` | `/api/v1/bls/jolts/revisions` |
| `eia_petroleum_imports_exports_and_movements_movements_of_crude_oil_and_selected_products_by_rail_eia_obb` | `/api/v1/eia/petroleum/imports_exports_and_movements/movements_of_crude_oil_and_selected_products_by_rail` |
| `tmx_fixedincome_prices_tmx_obb` | `/api/v1/tmx/fixedincome/prices` |
| `eia_petroleum_refining_and_processing_refinery_net_input_eia_obb` | `/api/v1/eia/petroleum/refining_and_processing/refinery_net_input` |
| `eia_natural_gas_consumption_end_use_natural_gas_consumption_by_end_use_eia_obb` | `/api/v1/eia/natural_gas/consumption_end_use/natural_gas_consumption_by_end_use` |
| `eia_coal_by_mine_by_plant_eia_obb` | `/api/v1/eia/coal/by_mine_by_plant` |
| `ecb_eligible_assets_ecb_obb` | `/api/v1/ecb/eligible_assets` |
| `eia_petroleum_refining_and_processing_refinery_blender_net_input_eia_obb` | `/api/v1/eia/petroleum/refining_and_processing/refinery_blender_net_input` |
| `eia_petroleum_refining_and_processing_refinery_net_production_eia_obb` | `/api/v1/eia/petroleum/refining_and_processing/refinery_net_production` |
| `eia_petroleum_refining_and_processing_natural_gas_plant_field_production_eia_obb` | `/api/v1/eia/petroleum/refining_and_processing/natural_gas_plant_field_production` |
| `imf_chokepoint_volume_imf_obb` | `/api/v1/imf/chokepoint_volume` |
| `eia_petroleum_imports_exports_and_movements_movements_by_tanker_and_barge_between_pad_districts_eia_obb` | `/api/v1/eia/petroleum/imports_exports_and_movements/movements_by_tanker_and_barge_between_pad_districts` |
| `eia_natural_gas_prices_natural_gas_prices_eia_obb` | `/api/v1/eia/natural_gas/prices/natural_gas_prices` |
| `eia_petroleum_prices_weekly_retail_gasoline_and_diesel_prices_eia_obb` | `/api/v1/eia/petroleum/prices/weekly_retail_gasoline_and_diesel_prices` |
| `eia_petroleum_status_report_eia_obb` | `/api/v1/eia/petroleum_status_report` |
| `cftc_fx_forward_trades_cftc_obb` | `/api/v1/cftc/fx_forward_trades` |
| `eia_natural_gas_summary_natural_gas_summary_eia_obb` | `/api/v1/eia/natural_gas/summary/natural_gas_summary` |
| `cftc_swap_trades_cftc_obb` | `/api/v1/cftc/swap_trades` |
| `ny_market_expectations_federal_reserve_obb` | `/api/v1/federal_reserve/ny/market_expectations` |
| `ffiec_institutions_federal_reserve_obb` | `/api/v1/federal_reserve/ffiec/institutions` |
| `finra_fixedincome_bonds_finra_obb` | `/api/v1/finra/fixedincome/bonds` |
| `finra_fixedincome_bond_prices_finra_obb` | `/api/v1/finra/fixedincome/bond_prices` |
| `ffiec_institution_structure_federal_reserve_obb` | `/api/v1/federal_reserve/ffiec/institution_structure` |

Settings (`credentials.env`): `OPENBQ_SSRM_WIDGETS` (path of that list, default `/workspace/ssrm_widgets.json`), `OPENBQ_SSRM_CACHE_BYTES` (default 3 GiB), `OPENBQ_SSRM_TTL` (seconds, default 900), `OPENBQ_SSRM_DEADLINE` (seconds per first acquisition, default 300). As with widget settings, restart the API after editing them.

The Funnel door admits a POST only on routes in its `ssrmRoutes`, which defaults to the 23 paths `/api<route>/ssrm`, one per row above, derived from `lanes/ssrm_widgets.json` (the gateway image copies that file); leave the setting out unless you mean to narrow it (`[]` turns SSRM through the door off). `funnel-gateway/ssrm-routes.test.mjs` checks the derived list (23 unique routes, each admitted for POST, a listed route's GET and an unlisted sibling refused). The door never passes od's `x-openbq-ssrm` cache marker to the client.

## Credentials and restart

### Demo keys

`credentials.demo.env` is committed and holds only public demo keys the providers publish
(api.data.gov's `DEMO_KEY` for EIA and Congress.gov, and from v9 EODHD's `demo` token, which covers only EODHD's demo symbols such as AAPL.US), so those cards answer before you have keys of
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

## BDOBB web preview door (v8, opt-in)

`docker compose -f docker-compose.yml -f docker-compose.v3.yml --profile web up -d` adds `funnel-gateway` and `rss-ticker` for BDOBB's browser preview: `/api` (the ODP catalogue, with the API's Basic pair injected), `/state` (per-user saved configuration), `/news` (approved feeds only, including the `/news/ws/news` socket and its signed tickets) and, with the `table` profile, `/table` (managed server-side tables, from v4; see [docs/v4/gateway-down.md](docs/v4/gateway-down.md)). There is no `/ai`. Nothing is public until you also swap `ts-config/serve.json` for `ts-config/serve-funnel.json` (with the v3 overlay: `serve-v3.json` for `serve-v3-funnel.json`), which funnels port 10000 alone; 443 (ODP), 8443 (the episode 3 reference) and 8088 (rss-ticker) stay tailnet-only. The table in [funnel-gateway/README.md](funnel-gateway/README.md#ports-and-serve-files) lists every port and serve file. Turn the API's lock on first (`OPENBB_API_AUTH=true`), and fill `gateway.env` and `gateway-config/settings.json` from their examples. See [funnel-gateway/README.md](funnel-gateway/README.md) and [docs/v8](docs/v8/news-relay-and-hidden-dashboards.md).

BDOBB's locked-widget bands sync as a hidden `docks` dashboard on `/pro/dash/sync/system/docks`. Key mode serves it here (`v3/openbq_settings.py`), and the Workspace companion serves it through `workspace/patches/004-system-dashboard.patch`.

## EODHD provider (v9)

Both API images (the `Dockerfile` stages `api` and `v3`) install the vendored openbq-eodhd extension 9.0.1, served as `obb.eodhd.*` on `/api/v1/eodhd/` with an `EODHD` app in `/apps.json`; put your own token in `credentials.env` as `EODHD_API_KEY`. Provenance, the 52 commands and the checks are in [v9/eodhd/README.md](v9/eodhd/README.md) and [docs/v9/eodhd-port.md](docs/v9/eodhd-port.md).

## Live grid and kdb+ (v10, opt-in)

`docker compose --profile live up -d` adds `live-grid` (the `live_grid` widget backend: EODHD websocket quotes, symbol metadata, bars and the tick chart) and `openbq-kdb` (the kdb+ tick cache it records into: Adventures-OpenBQ/openbq-kdb, vendored in `v10/kdb/source`, running on a KDB-X image you supply). The default kdb image is the maintainer's private one (`ghcr.io/artcashin/kdb-x:amd64@sha256:013490f90a166e0863651f2c8a7f5d24e8d1beec68d2e3e541c1a2281653a77c`, linux/amd64 only); it is not public and never will be, because kdb+ is proprietary. Set `KDB_IMAGE` to your own image, or build one from your licensed KDB-X with `-f compose.kdb-build.yml` (below). The default stack is unchanged. Neither service has a host port or a Serve entry. Bring your own KX licence (`kdb-license/kc.lic`, git-ignored, mounted read-only; or set `KDB_LICENSE_DIR` to a directory outside this repository, e.g. `../my-private-checkout/kdb-license`; see `.env.example`). Crash recovery is always on: q runs the repository's `v10/kdb/source/q/startup.q` and `persist.q` (mounted read-only), logs every tick to `/data/logs/tlog_<date>` on the named volume `kdb-data`, and replays the last three days' logs when it restarts (a torn tail is cut back to its last whole chunk), so a restarted kdb comes back with the day (logs roll daily and are kept 7 days). Without kdb, live-grid still serves quotes and history; it reads history from `/api/v1/eodhd/` and needs `EODHD_API_KEY`. BDOBB's web preview reaches it through the gateway's `/grid` family: run both profiles and set `"liveGrid": true` in `gateway-config/settings.json`. See [live-grid/README.md](live-grid/README.md), [funnel-gateway/README.md](funnel-gateway/README.md) and [docs/v10/live-grid-kdb-port.md](docs/v10/live-grid-kdb-port.md).

The same profile adds the S3 tier (by user ruling, from the donor line): `rustfs` (the S3 store, the upstream Apache-2.0 image `rustfs/rustfs:1.0.1`, bridge only, no port, no console), `rustfs-init` (creates the bucket over the S3 API) and `eod-dump` (at 00:05 UTC it flushes the UTC day kdb held into a Delta Lake table per symbol and day, library `ticks_live`). live-grid's chart reads whole past days back from that store, so a 1m chart over last week is built from the recorded ticks rather than provider history. Fill `rustfs.env` first (`cp rustfs.env.example rustfs.env && chmod 600 rustfs.env`; a long random root pair, written twice, as `RUSTFS_*` and `DELTA_S3_*`); without it rustfs logs a refusal once and idles unhealthy (no store, no restart loop), and kdb and live-grid run without the store. `eod.env` is optional. No MinIO software is used. The store is persistent on the host: its data lives in `./rustfs-data` (git-ignored; set `RUSTFS_DATA_DIR` in the shell or `.env` to use another disk), so it survives container recreation, image upgrades and `docker compose down -v`; the one-shot `rustfs-perms` makes that directory belong to RustFS's uid 10001 before `rustfs` starts. To build the kdb image yourself from KX's distribution (for amd64 or arm64) instead of pulling the private default, add `-f compose.kdb-build.yml` (recipe in [kdb-x/](kdb-x/README.md); it ships no KX software and no licence).

## Public repository checks

Enable the local gates after cloning:

```sh
git config core.hooksPath .githooks
python3 scripts/check-public.py --history
```

Commits scan tracked, staged and unignored files; pushes also scan the history reachable from the pushed refs; CI and a bare `--history` scan every branch and tag. Local deployment evidence and the machine-specific `scripts/scrub-private-patterns.txt` remain ignored. Reports use placeholder hostnames and addresses. The scanner reports filenames and finding categories, never matched values.

Real `credentials.env` files may be used on the NAS, but stay out of Git and Docker build contexts. Example credentials must contain empty values or obvious placeholders; an `.example` suffix does not make a real key safe to publish. The one exception is `credentials.demo.env`, whose public demo values `scripts/check-public.py` allows by exact name and value. Screenshots still need visual review before publication.

## Episode 3 candidate: BDOBB and the reference backend

The stack's API image includes [our original yfinance extension](v3/yfinance/README.md),
BDOBB's settings API and the v4 calendar and fiscal-year routes; `docker-compose.yml`
alone builds it.
The optional [v3 Compose overlay](docker-compose.v3.yml) adds the
[OpenBQ reference backend](examples/episode3/README.md) with fictional pivot
widgets. The shared private Tailscale sidecar serves ODP on 443 and the reference
backend on 8443, both tailnet-only. No NAS host ports or public Funnel are enabled
(the v8 `web` profile's door, Funnel port 10000, runs beside it through
`ts-config/serve-v3-funnel.json`).

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

The reference `/apps.json` advertises 74 self-contained cards with zero missing
widget references. Its `/bundle.apps.json` download adds the keyless ODP market
examples for an 80-card BDOBB file import. The two Episode 3 app entries carry
the BDOBB logo in standard image fields. Workspace is an optional Episode 2
comparison, not a prerequisite for this setup.

Released as `v3.0.0` with BDOBB v3.0.0: `openbq-local:3.0.0` and
`openbq-key-maint:3.0.0`, both built from this checkout, are the images the 2026-10-15 regression ran on a NAS.

The reference recipe carries forward the previously qualified PDF repair from `bdobb-dev/backends-for-openbb` commit `32615f789f9423ea14d3f95003da250f4ef5bcfc`. Sample and Bitcoin PDFs use immutable GitHub raw URLs because the original S3 bucket returns AllAccessDisabled. Downloaded bytes match the pinned upstream fixtures; this changes asset transport, not PDF content.

## Episode 6: Rita and MCP

The optional [v6 Compose overlay](docker-compose.v6.yml) adds OpenBQ Rita (the
agent BDOBB talks to) and the OpenBB MCP server. Both are built on the machine
that runs them; nothing is pulled from a registry. Rita's recipe is
`Adventures-OpenBQ/agent-rita-bdobb`, which patches public
[openbq-org/agent-rita](https://github.com/openbq-org/agent-rita). MCP is
`openbb-mcp-server` 2.0.1 installed on this release's `openbq-local` API image,
from [mcp/](mcp/Dockerfile). The shared
private Tailscale sidecar serves Rita on 10443 and MCP on 11443, next to ODP on
443 and the reference backend on 8443. No host ports or Funnel are enabled.

```sh
# Rita: build openbq-rita:6.0.0 once, next to this checkout (needs git and Docker).
git clone --branch v6.0.0 https://github.com/Adventures-OpenBQ/agent-rita-bdobb.git ../agent-rita-bdobb
../agent-rita-bdobb/scripts/build.sh
cp rita.env.example rita.env   # then chmod 600 and fill it in
docker compose -f docker-compose.yml -f docker-compose.v3.yml -f docker-compose.v6.yml config --quiet
# MCP: builds openbq-api first, then openbq-mcp on top of it.
docker compose -f docker-compose.yml -f docker-compose.v3.yml -f docker-compose.v6.yml build openbq-api openbq-mcp
docker compose -f docker-compose.yml -f docker-compose.v3.yml -f docker-compose.v6.yml up -d
```

An existing, customised stack should edit its live `TS_SERVE_CONFIG` file in
place, keeping its existing ports, instead of switching to `ts-config/serve-v6.json`:
switching recreates tailscale (and Rita with it), and `serve-v6.json` drops extra
ports such as 9443.
`serve-v6.json` also has no Funnel door: with the [web preview door](#bdobb-web-preview-door-v4-opt-in),
add the port 10000 entries from `ts-config/serve-v3-funnel.json` to the live file.

Tailscale Service names for Rita and MCP are opt-in. `ts-config/serve-v6-services.json` is
`serve-v6-keys.json` plus `svc:openbq-rita` (`https://openbq-rita.<your-tailnet>.ts.net`) and
`svc:openbq-mcp` (`https://openbq-mcp.<your-tailnet>.ts.net/mcp`), proxied to the same targets as
10443 and 11443. Those ports stay served, so both addresses work. To use it, create the
Services `svc:openbq-keys`, `svc:openbq-rita` and `svc:openbq-mcp` in your tailnet's admin
console and approve this node as their host (a Service host must be a tagged node), replace `<your-tailnet>` in the file, point the
`tailscale` service's `TS_SERVE_CONFIG` at `/config/serve-v6-services.json`, and recreate
tailscale and then `openbq-rita` (below). Until the Services exist, keep `serve-v6.json` or
`serve-v6-keys.json`: a serve file that names a Service the tailnet does not have can be
refused. The Services have no authentication of their own either; restrict them with a
tailnet ACL, as for the ports.

Rita needs an OpenAI-compatible model endpoint, typically on the tailnet.
Containers on a Docker bridge network do not get Tailscale MagicDNS, so Rita
runs in the Tailscale sidecar's network namespace (`network_mode:
"service:tailscale"`), mirroring the host networking of a Rita that runs
directly on a tailnet machine. Its `/etc/resolv.conf` is the tracked
[rita-resolv.conf](rita-resolv.conf), which points at Tailscale's MagicDNS
resolver. Serve reaches Rita on `127.0.0.1:7777` inside that namespace. If the
tailscale container is recreated, recreate `openbq-rita` too
(`docker compose -f docker-compose.yml -f docker-compose.v3.yml -f docker-compose.v6.yml up -d --force-recreate openbq-rita`); otherwise it is left
in the old, dead namespace. MCP advertises the 10 tool-discovery tools; categories load on demand.
Rita carries the agent-rita-bdobb patches through 0012. MCP drops the separate
trading-calendar extension the first Episode 6 image carried: from v4 the API image's
own `calendar` routes (`v4/routes`) serve `obb.calendar`, and the build checks it.
See VERIFICATION.md.

MCP runs ODP in-process, so it loads the same provider keys as the API
(`credentials.demo.env`, then your `credentials.env`) and the same 16g memory cap;
its in-process calls never ask for the API's Basic auth. MCP on 11443 has no
authentication of its own, even with the API's lock on: any tailnet device that can
reach the `openbq` node can call its tools and spend those keys. Restrict 11443 with a
tailnet ACL, as for Rita on 10443, which has no authentication either. Funnel never
exposes either port. Rita listens on the namespace's wildcard address, so it also
answers tailnet devices as plain HTTP on the node's port 7777; a tailnet ACL is what covers it.
Released in `v6.0.0`, with BDOBB v6.0.0.

### Component licenses

The first-party key-maint component is AGPL-3.0-only. Where included, the first-party rss-ticker component is also AGPL-3.0-only. Each component carries its own LICENSE and LICENSING.md; earlier grants and third-party notices are preserved. Other components retain their stated licenses.
