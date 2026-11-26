# V10 and later: live-grid deployment preflight

Build this release's images locally under the reader recipes. No maintainer
registry login or prebuilt backend/kdb image is required. Run
`scripts/live_grid_preflight.py --deploy` for the opt-in live profile deployment;
it gates continuation on the chosen immutable image and application readiness.
The default API setup remains separate.

`live-grid/runtime-images.json` deliberately has no V10 image pin. Supply `--image`
from your own completed build. A local full image ID `sha256:<64 lowercase hex>`
never triggers a pull. An explicit registry `repository@sha256:<64 lowercase hex>`
is also supported, including an operator's private GHCR repository; only that form
is pulled during ensure. Check-only never pulls either form. Mutable tags, short
IDs and absent release pins are refused before contacting Docker. Image selection
is not a claim that its source, architecture, data entitlement or behavior has
already been qualified.

## Local build and guarded deployment

Provision the documented private env, gateway settings, KX license and optional
secured-chart auth files first. Follow the local KX base build and then its
secured derivative in [chart deployment](chart-stream-deployment.md), using the
same overlays throughout. No license or credential belongs in an image/build arg.

With the required base and external public dependency images available, build
the selected images locally. The following example selects secured charts; retain
any other overlays required by your installation:

```sh
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web config --quiet
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web build openbq-kdb live-grid eod-dump funnel-gateway
# Start the selected project's API/q dependencies before the application probe.
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web up -d openbq-api openbq-kdb
# The final --deploy is --no-build --pull never; obtain external public dependencies explicitly if absent.
docker compose -f docker-compose.yml --profile live pull rustfs
LIVE_GRID_IMAGE_ID="$(docker image inspect openbq-live-grid:10.0.0 --format '{{.Id}}')"
python3 scripts/live_grid_preflight.py --release 10.0.0 \
  --image "$LIVE_GRID_IMAGE_ID" --file docker-compose.yml \
  --file compose.chart-stream.yml --profile web --require-chart-stream --deploy
```

For a quote-only deployment, select its matching recipe and omit
`--require-chart-stream`; do not report its accepted-stream capability as verified.
The image ID must belong to the intended platform and your reviewed build. A
registry operator may instead supply their own full `repository@sha256` reference;
private registry authorization is their optional setup, never a reader prerequisite.

## Existing service check

Use the same directory, project, overlays, additional profiles and local image ID:

```sh
python3 scripts/live_grid_preflight.py --release 10.0.0 \
  --image "$LIVE_GRID_IMAGE_ID" --file docker-compose.yml \
  --file compose.chart-stream.yml --profile web --check-only --require-chart-stream
```

`--directory`, repeated `--file` / `--env-file`, `--project-name`, and `--context`
select the environment explicitly. Paths must be accessible to that invocation
and its daemon. The wrapper does not discover or modify unrelated projects.
Credentials are read only by the probe inside the selected container, with the
same Basic-auth environment variables and truthy values as the application; raw
Docker/Compose errors are withheld from output.

## What the gate does

Ensure inspects the supplied image and compares its platform image ID with the
selected project's container. It recreates only that live-grid service when
missing, stopped, stale or unhealthy. If defined, the project's live-grid-perms
initializer runs first using the same image. Existing API/q dependencies must
already be started. A correct running service is probed without recreation.

The probe requires HTTP 200, health `status: ok`, and live-grid plus Day Chart
discovery. With `--require-chart-stream`, the current Live Chart must additionally
advertise `extra_metadata.chart_stream_v1: true`. A degraded health body is refused.
This checks readiness and advertised capability, not actual provider data or
release-wide image qualification. Readiness polling defaults to 90 seconds and
accepts only finite values from 0 to 600; individual Docker operations also have
finite command deadlines. Failure blocks continuation.

Ensure retains `.openbq/live-grid-image-<content-hash>.json` so Compose labels keep
referencing an existing image override. Check-only uses a temporary override and
makes no Docker mutations. The final `--deploy` runs the selected Compose project
with `up -d --no-build --pull never` only after readiness passes, then checks again.
Releases older than V10 bypass the live-grid gate.

Raw `docker compose up` is available to an operator but **bypasses this wrapper**;
it must not be described as guarded deployment. Automated opt-in live deployment
should call the documented wrapper with `--deploy` and stop on nonzero status.
Unit tests cover fake Docker and HTTP boundaries; they do not qualify a running
service, a particular host, an image candidate or a provider entitlement.
