# Secured v10 chart stream and Funnel deployment

This is an opt-in v10 chart source integration, also ported to current main. `v10/kdb/source.json`
records the exact KDB source commit; a null tag means no release tag exists.
Use the matched CLIENT branch `codex/v10-chart-stream-api` and HOST branch
`codex/v10-kdb-chart-api`. charts/v12 remains a later consumer.

## Backend

Keep the existing licensed q base image and license mount. The overlay derives
an image with Python for the stdlib bootstrap and copies the pinned server
package; no license or credentials enter the build context. Build HOST images
locally so live-grid and eod-dump install the same vendored client package.

Create a private `kdb-auth` directory (or set `KDB_AUTH_DIR`). Provision distinct
base64url tokens of 32–256 characters. `passwords` contains one `username:token`
line for each principal; `live-grid.token` and `eod-export.token` contain just
the matching token. All three token files must be regular files with mode 0600. Make
`live-grid.token` readable by container uid 10001 (its sole owner); the q and
exporter files must be readable by their container root process. A host-user
0600 file mounted into an unprivileged container is insufficient. Verify the
ownership mapping on the deployment host rather than widening permissions.
Copy `kdb-secured/roles.example.json` to `roles.json`; its principals must exactly
match the passwords file. Do not put these values into shell arguments or logs.
The live-grid role set includes recorder, query/cache, chart and diagnostics;
the exporter has only export. The q launcher refuses malformed policy/credentials.

Starting from the existing v10 deployment and its configured env files:

```sh
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web config --quiet
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web build openbq-kdb live-grid eod-dump funnel-gateway
# Start the selected project's API/q dependencies for the readiness probe.
docker compose -f docker-compose.yml -f compose.chart-stream.yml --profile live --profile web up -d openbq-api openbq-kdb
docker compose -f docker-compose.yml --profile live pull rustfs
LIVE_GRID_IMAGE_ID="$(docker image inspect openbq-live-grid:10.0.0 --format '{{.Id}}')"
python3 scripts/live_grid_preflight.py --release 10.0.0 --image "$LIVE_GRID_IMAGE_ID" \
  --file docker-compose.yml --file compose.chart-stream.yml --profile web \
  --require-chart-stream --deploy
```

Preserve any other overlays required by that deployment in every command. The
[preflight guide](live-grid-preflight.md) describes local-image selection and the
bootstrap sequence. Raw Compose deployment remains an operator alternative that
bypasses the gate; it is not guarded startup.
`openbq-kdb` uses secured tickplant mode, not the ping-only qualification mode.
Its existing `/data` volume and four-column durable tick logs are preserved.
An API authentication, authorization or protocol error is terminal for that
connection; it must not trigger a legacy or anonymous retry. Recorder policy
failures retain valid batches in the spool instead of poisoning/quarantining
those batches. The exporter also uses the named API when credentials are set.

The overlay sets `LIVE_GRID_CHART_STREAM=true` and opts into the bounded
structured diagnostic pump with `LIVE_GRID_KDB_DIAGNOSTICS=true`. Discovery advertises protocol
v1 on the existing Live Chart widget only after source qualification. A startup
outage retries qualification; after successful qualification an outage keeps the
protocol identity and triggers recovery rather than changing stream semantics.
q remains on internal `live-private`, with no published port. The gateway's
chart route requires backend Basic authentication, including deployments whose
legacy live-grid routes allow anonymous access.

## Vercel and Funnel

Use the CLIENT `web/CHART-FUNNEL.md` instructions for the existing Vercel preview
function. Set server-side `APP_ORIGIN` to the canonical Vercel HTTPS origin,
`BACKEND_GATEWAY_ORIGIN` to the Funnel HTTPS origin, and
`BACKEND_GATEWAY_TOKEN` to the existing HOST machine credential. Preserve OAuth,
viewer allowlist and session settings. The machine token and q token never
belong in public build variables or browser storage.

In the gateway's full settings set `origin` to that Funnel origin,
`previewOrigin` to the exact Vercel origin and `liveGrid` to true. The CLIENT
must include the matching vendored HOST policy. It obtains a short-lived,
single-use, origin-bound chart ticket from its same-origin `/socket-ticket`.
Its WebSocket then connects directly to
`wss://${FUNNEL_HOST}:10000/grid/chart_stream_ws`; Vercel handles session
and ticket requests, not the long-lived socket. Expiry closes the public socket
and reconnect obtains a new ticket and resumes its checkpoint or resnapshots.

Preserve the existing Tailscale node configuration and use
`ts-config/serve-funnel.json` (or the matching v3 Funnel file) to publish the
gateway on port 10000. Follow `funnel-gateway/README.md` for activation and keep
other Serve routes intact. Never route Funnel directly to q or live-grid.
Tailscale requires Funnel permission, HTTPS and MagicDNS; current limits and
setup are in [Tailscale documentation](https://tailscale.com/docs/features/tailscale-funnel).

## Qualification and rollout

Local tests cover credential rejection, named role dispatch, durability,
snapshot/accepted batches, cursor resume/reset, late candle replacement,
backpressure, broker/session/ticket/origin checks and Compose compilation.
The native test runs a licensed q child through the real Python store and
live-grid TCP WebSocket endpoint; it is not a deployed Funnel demo.

Before calling a deployment qualified, record the paired revisions and check
an allowed signed-in viewer outside the tailnet, anonymous/expired rejection,
fresh-ticket reconnect, slow-client reset/resnapshot, and late candle revision.
Check q is unreachable publicly. Keep the prior image/config revisions for
rollback; changing source epochs requires a fresh snapshot. Preserve tick logs
and spool files during rollback. Do not run legacy arbitrary-eval clients
against the secured listener.

Linux amd64/arm64 derived-image startup, actual Vercel-to-Funnel browser behavior,
and the normal-load latency/ingestion regression gates remain deployment
qualification items. No Funnel activation, Vercel deployment, push or release is
performed by adding these files.
