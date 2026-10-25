# Managed native tables (local build)

The optional `table` profile adds a private native service. Source authority is
`Adventures-OpenBQ/bdobb`; `source.lock.json` pins its exact local commit, Git tree
and Dockerfile hash. Both repositories' commits can be unpushed. This configuration
does not name a published service image or fetch an unavailable remote SHA.

From this Docker checkout, with the paired bdobb checkout present:

```sh
node table-service/prepare-source.mjs /absolute/bdobb-checkout /absolute/new-table-context
docker compose --env-file /absolute/new-table-context.env --profile table build table-service
# Compare the revision/tree labels and /app/source.json with source.lock.json.
docker image inspect bdobb-table-service:local --format '{{json .Config.Labels}}'
docker run --rm --entrypoint cat bdobb-table-service:local /app/source.json
```

`prepare-source.mjs` exports only the pinned Git commit, independently of staged or
unstaged work, verifies its tree and Dockerfile, and records the archive SHA-256.
It refuses an existing output directory. There is one native implementation; the
Docker repository does not copy or fork Rust code. The build uses locked Cargo and
pnpm dependencies, Rust 1.98.1, ICU 78.3 and Node 26.10.0. The runtime contains only
the ingestion bundle plus the dereferenced xlsx 0.20.3 package, native binaries,
Node, ICU and license notices. Distribution package updates mean image bytes are
not guaranteed identical. Record the built image digest with release evidence.

## Operator configuration

Create private `table-config` (mode 0700, readable by UID 10001) and copy
`settings.example.json` to `table-config/settings.json` (0600, owner 10001).
Generate three distinct random base64url credentials: the ordinary gateway bearer,
`TABLE_RELAY_TOKEN` (web server + gateway only), and `TABLE_GATEWAY_TOKEN` (gateway +
native service only). Put the latter into private `auth.gateway_token` and the same
value in gateway.env. Never put either private credential into desktop settings,
browser bootstrap, cards, URLs or a public `.env` file. Existing gateway.env still
requires its ordinary token and OpenBB Basic credentials.

Add to private gateway settings:

```json
{
  "tableService": true,
  "tableDesktopPrincipal": "desktop:owner",
  "tableTimeoutMs": 65000
}
```

Merge these into the existing object; keep its required origin and existing policy.
`tableService` is an explicit availability switch; false/unset makes table requests
503. Its origin is fixed at `http://table-service:8080`. Omit
`tableDesktopPrincipal` to disable shared-token desktop table access. Ordinary shared
bearer requests always map to that configured desktop principal; ownership headers
are discarded. A forwarded `github:<immutable account ID>` requires the separate
private relay credential as well as the ordinary bearer. Invalid/duplicate assertions
fail closed. Gateway injects only its private service credential and verified owner;
it never passes caller auth, cookies or identity credentials to the native service.

Configure the trusted web server with the same `TABLE_RELAY_TOKEN` and its existing
BACKEND_GATEWAY_ORIGIN/TOKEN. It derives the principal from the authenticated account
ID, preserves CSRF enforcement, and seeds same-origin `/table` discovery for fresh
settings. `TABLE_TIMEOUT_MS` optionally lowers its 65-second deadline. Desktop
Connections uses `<gateway origin>/table` with ordinary Authorization Bearer auth;
use Ask at startup to avoid persisting the credential. GitHub and desktop namespaces
remain distinct, and source ownership survives login and service restarts.

Only the explicit native health/capabilities/widgets, source upload/backend/deletion,
session open/command/derive/cancel/dispose and export/batch/deletion endpoints are
admitted. Upload POST <=16 MiB; JSON POST <=2 MiB; GET/DELETE have no body. Export GET
requires exactly one nonnegative sequence. Each JSON response is bounded at 8 MiB
and buffered to completion, so truncation, overflow and timeout never publish a
partial success. Status-only sanitized failures retain 400/401/404/409/410/413/429/503;
other upstream failures become 502. Credentials and upstream error bodies never relay.
No mutation is retried automatically. Configured deadlines are 1000–65000 ms.
SSRM POSTs (`ssrmRoutes`) have their own `ssrmTimeoutMs`, default 170000 and at most
300000 (od's `OPENBQ_SSRM_DEADLINE`), because a first page acquires the whole result.

Cancellation and cleanup remain reachable during ordinary HTTP saturation. Each
of the web relay, gateway and service reserves **two concurrent control requests**
for exact, query-free POST session cancel and DELETE session/export routes only.
No other route borrows this capacity. The web relay retains four ordinary table
slots and the gateway `maxConcurrent`; neither has a per-minute allowance (both
removed 2026-10-17).
The service retains `max_http_requests` ordinary slots, plus two authenticated
control slots; it retains its body/job deadlines and owner checks. Control limits
return 429 at relays and the existing 413 resource-limit response at the service.
Success, error, disconnect and deadlines release the associated lane's capacity.

Standard provider SSRM POSTs are exact entries in `ssrmRoutes`, e.g.
`/api/api/v1/reviewed_provider/rows`; review each actual provider endpoint before
registering it. Unset, it defaults to the 23 routes od serves
(`lanes/ssrm_widgets.json` as door paths); set it
only to narrow that list, and `[]` turns SSRM through the door off. The web `SSRM_ROUTES_JSON` must contain the same paths. Query rules
remain the existing bounded API policy; these POSTs use the existing injected Basic
credential and the concurrency cap. No broad POST prefix or generic proxy
is introduced. Existing GET API and state routes retain their policies.

## Private runtime and verification

The service has no published host port, runs as 10001 with read-only root, all
capabilities dropped and no-new-privileges. Only the gateway joins its private ingress
bridge. A separate egress bridge permits explicitly configured backend acquisition.
The named `table-sources` volume persists private uploads/catalogs. Do not remove the
volume during restart tests. A fresh volume inherits image ownership; for an existing
volume, provision ownership explicitly. `table-config` may also hold private backend
acquisition configuration; leave backend_config null for upload-only operation.

The configurable qualification profile uses an 8 GiB container ceiling, 7 GiB
global reservations and 6 GiB per principal, two compute workers, four admitted
jobs and four HTTP exchanges. It admits 2 MiB uploads, 8 MiB encoded sources,
64 input / 256 output columns, 100-row blocks, 1 MiB batches and 64 MiB retained
result estimates. The 20,000-row ceiling is an admission rule, not tested capacity.
Actual workloads and limits are recorded in the paired bdobb qualification evidence.

Inputs reserve bounded boxed JSON plus 64 KiB metadata; each real worker still
reserves its full 512 MiB Linux address-space bound, three frames, cache and
thread headroom. Job and startup reservations remain separate. Node's 128 MiB
heap is only its V8 heap; external allocations also consume the container cap.
A browser hard reload may retain abandoned sessions until expiry and temporarily
consume more capacity. Close unused dashboards, or wait for expiry before reopening
when admission refuses. Do not increase one ceiling without reviewing the others.

The final pinned image is **unqualified**: the earlier exact-source image build
failed at apt with insufficient Docker VM space. No unrelated Docker cache or
volume was pruned, and that unchanged failure was not retried. A task-owned,
host-backed Linux runtime verifies the service and health script with a non-root
host UID, private catalog, read-only root and enforced memory cap. It does not
verify the assembled image, image UID 10001, named-volume initialization or
release binaries. Those checks remain required before release.

Before any local bring-up, validate operator env/settings and run:

```sh
node --test funnel-gateway/*.test.mjs
docker compose --env-file /absolute/new-table-context.env --profile web --profile table config --quiet
```

The image build must succeed before recording image qualification. Then, on an isolated
test stack, check authenticated health, upload CSV, open/apply, linked derive, bounded
export batches, foreign-owner refusals, restart with the same volume, reopen the saved
source, and confirm old sessions are unavailable. Inspect worker `/proc/<pid>/limits`
for the configured hard address-space cap. An equivalent host-backed Linux runtime
smoke can qualify behavior when Docker storage is full; it cannot qualify image layers,
image healthcheck packaging or production deployment. Never prune unrelated Docker
data to make this test fit.
