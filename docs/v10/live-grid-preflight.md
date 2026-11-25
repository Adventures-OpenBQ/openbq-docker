# V10 and later: live-grid deployment preflight

Use `scripts/live_grid_preflight.py` as the gate before a v10+ deployment. The
release's expected image is an immutable registry digest, not a mutable `latest`
tag. `live-grid/runtime-images.json` records the current qualified v10 candidate;
each later major release needs its own pin, or an explicit `--image` supplied by
that release's deployment configuration. Updating the pin belongs to the release
qualification process.

## Existing service check

Run on the Docker host, in the Compose project that owns live-grid:

```sh
python3 scripts/live_grid_preflight.py --release 10.0.0 \
  --file docker-compose.yml --file compose.chart-stream.yml \
  --check-only --require-chart-stream
```

For the shared 64 GB Mac runtime, use its `~/Services/openbq-live-grid` directory
and `--file compose.yaml`. Run there over SSH. `--context` selects a Docker context
when Compose configuration and bind paths are available to that invocation.
Credentials remain in private environment files; the check reads them inside the
container and never includes them in command arguments or receipts.

## Ensure before deployment

Omit `--check-only` to pull the release pin, compare the running container's image
ID with that platform's image, and recreate only the selected project's live-grid
when missing, stopped, stale or unhealthy. If the project defines
`live-grid-perms`, its one-shot initializer runs first. Existing API/kdb services
are not recreated by the preflight; configure and start those dependencies before
initial live-grid bootstrap. Their readiness is additionally required when
`--require-chart-stream` is set.

Pass `--deploy` to run that same selected Compose project's `up -d --no-build`
only after the gate succeeds. Alternatively, call the gate from an environment's
existing deployment launcher and stop on its nonzero exit code before continuing.
Use `--directory`, repeated `--file` / `--env-file`, and `--project-name` to select
the environment explicitly. It does not discover or modify unrelated projects.

A normal ensure stores the image override at
`.openbq/live-grid-image-<content-hash>.json`, so the running container's Compose labels
reference a retained configuration. Check-only uses a temporary override and makes
no Docker mutations. Raw `docker compose up` bypasses this wrapper; setup and
release automation must invoke the gate rather than claiming raw Compose is guarded.

HTTP 200 with application status `degraded` is rejected. Health/discovery are polled with a bounded readiness timeout (default 90 seconds).
Registry/Compose operations have command deadlines. Registry authorization, a
missing release pin, wrong container image, a failed health check or an unavailable
application blocks continuation. A quote-only deployment may omit
`--require-chart-stream`; its kdb capability is not falsely reported as qualified.
Releases older than v10 bypass the live-grid gate.

## Qualification

Tests exercise missing/stopped/stale/unhealthy services, unchanged healthy service,
check-only isolation, volume initialization, failed readiness blocking deployment,
per-release pins, older release bypass, and retained image overrides. The isolated
64 GB Mac service also passed a real check-only probe without recreation.
