# Current main build and regression controls

These controls apply to the combined main sources. Earlier release receipts do
not qualify a new build. Keep the same Compose files, profiles, project, and image
identities throughout a check.

## Validate isolation without starting services

From the repository root:

```sh
python3 scripts/compose-run.py --regression --plan --service eod-dump \
  --report private/eod-plan.json
```

The launcher reads Compose's resolved structural model without resolving service
env files. A plan closes over runtime dependencies, replaces writable directory
state with project-owned volumes, and retains normal volume initialization. It
creates no containers, volumes, networks, or build outputs. Use a new private
receipt path for every invocation; existing evidence is never overwritten.

An actual run requires a check command after `--` and exact image-ID bindings for
prebuilt dependencies supplied with `--verified-images`. It uses a new project,
ordinary input-aware build caching, immutable startup image IDs, and cleanup
limited to resources carrying that project's ownership labels. Unsupported
published ports, foreign namespaces, external state, and ambiguous writable file
binds are refused. Raw Docker diagnostics and resolved configuration values are
kept out of the receipt and console.

## Gate an opt-in live-grid deployment

Build the selected recipes and start their API/q dependencies before invoking
the application readiness gate. Supply the immutable image ID from that build:

```sh
python3 scripts/live_grid_preflight.py --release 11.0.0 \
  --image "$GRID_IMAGE_ID" --file docker-compose.yml \
  --file compose.chart-stream.yml --profile web \
  --require-chart-stream --check-only
```

Use the same arguments with `--deploy` instead of `--check-only` to continue with
the selected project's `up -d --no-build --pull never` only after readiness passes.
The gate checks the expected image, running/healthy state, application health and
widget discovery. `--require-chart-stream` also requires the advertised accepted
chart-stream capability. It does not establish provider entitlement or qualify
the source/build as a whole.

`live-grid/runtime-images.json` is deliberately empty until current-main images
have fresh qualification evidence. A release cannot inherit an older release's
pin. A full local `sha256:` image ID never triggers a pull; an explicitly supplied
registry digest can be pulled by ensure, while check-only never pulls or recreates
services. Mutable tags and short IDs are refused.
