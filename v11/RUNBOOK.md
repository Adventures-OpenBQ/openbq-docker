# v11 offline recovery rehearsal

Use the standalone P repository's `temporaldb.recovery` APIs or
`uv run --frozen python scripts/restore_check.py ACTION --config CONFIG.json`.
These are trusted administrative operations. Only use a locally reviewed bundle:
PostgreSQL archives contain executable database definitions. Keep the source and
recovery target isolated, with ingestion, expiry and cleanup stopped. Recovery
never automatically switches deployment traffic or starts ingestion.

## Bundle

Create explicit fixture run references with `ProtectedRun`: UUID, exact scope,
accepted input/output manifest, catalog ID, query kind (`gold` or `ticks`), temporal
context, typed tick selection, expected result hash/row count and ordering.
Gold replay is the saved view at its exact input snapshot, ordered by logical
key; tick replay preserves the selected ordering and rejects legacy inclusion.
Hash canonical JSON (`sort_keys=True`, compact separators, `default=str`) over
the complete ordered result list. Retain each reference with
`PinStore.hold(manifest, run_id, True)` before backup. For application audits use `AuditService.recovery_run(scope, run_id)` to bind
the actual protected execution, query revision, full dependency closure and
retained runnable environment. Low-level `ProtectedRun` fixtures remain available
for explicit Gold/tick checks; they are not substitutes for application audits.

`BundleConfig` requires a new bundle path, an administrative `PostgresEndpoint`,
a supplied S3 client, explicit dedicated bucket names/catalog specs, locked
extension directory, actual run references, artifact paths, source label,
source S3 connection configurator and `writers_stopped=True`. Source results and
snapshot versions are checked first. A PostgreSQL exported snapshot backs the
custom dump; all user-table row counts/content hashes include inlined catalog
data and complete control authority. All named bucket objects are copied and
hashed. A final database/object-inventory recheck rejects detected concurrent
changes. The operator's cross-store stop is required; the tool does not claim
cross-store atomic backup. Only a complete bundle receives `manifest.json`.

The command's credential-free JSON configuration uses these fields:

```json
{
  "label": "fixture-source",
  "bundle": "/tmp/task9-bundle",
  "postgres_dsn_env": "TASK9_SOURCE_ADMIN_DSN",
  "postgres_tool_dsn_env": "TASK9_SOURCE_TOOL_DSN",
  "postgres_command_prefix": ["docker", "exec", "-i", "--env", "PGPASSWORD", "SOURCE_FIXTURE_POSTGRES_CONTAINER"],
  "s3": {"endpoint_env": "TASK9_SOURCE_S3_ENDPOINT", "region": "us-east-1"},
  "extension_directory": "/tmp/locked-extensions",
  "runs_file": "/tmp/fixture-runs.json",
  "buckets": ["temporaldb-fixture"],
  "catalogs": {"hot": {"metadata_schema": "fixture_hot", "data_path": "s3://temporaldb-fixture/hot/"}},
  "artifacts": {"uv.lock": "/absolute/P/uv.lock", "compose.yaml": "/absolute/fixture-compose.yaml"}
}
```

Use the exact dedicated container ID if PostgreSQL tools run inside Compose;
the external tool DSN names its internal address. For local matching PostgreSQL
tools, omit the command prefix/tool DSN. DSNs and all AWS credentials/session
tokens stay in the environment/credential chain, outside bundles and configs.
`pg_dump` uses no role-password dump; the target's role memberships/logins must
be provisioned separately. Preserve the application NOLOGIN roles and ACLs.
Run `... restore_check.py bundle --config SOURCE.json --writers-stopped` only
after independently stopping the named writers and maintenance.

## Restore and replay

Start a separately named, task-owned fixture Compose project using pinned images,
new volumes and ephemeral loopback ports. Never use shared prune. The repository
fixture uses `compose.test.yaml` plus `compose.test.tmpfs.yaml`; the 256MiB PG
RAM volume is disposable and does not establish durable recovery performance.
Use a different PostgreSQL cluster and S3 endpoint, matching versions/platform.
No user tables or objects may exist at the target; restoration never cleans or
overwrites an existing store. The same bucket names/keys are restored at the new
endpoint. Do not point restored lake readers at source S3 credentials/endpoints.

Before restore, include PostgreSQL lock-table capacity in the acquisition/recovery
forecast alongside data, indexes, WAL, temporary files and memory. The final
accumulated fixture dump had **4,955 tables**: atomic `pg_restore` failed at the
default `max_locks_per_transaction=64` with `out of shared memory`, while the exact
dump succeeded with 512 and a 1 GiB data fixture. This does not establish512 as a
universal setting; size for the real table/index inventory, concurrency,
`max_connections` and `max_prepared_transactions`, then rehearse it. The separate
256MiB fixture ENOSPC failure concerned data/temp-file capacity, not this lock limit.

A database operator must configure sufficient `max_locks_per_transaction`, restart
PostgreSQL for that setting to take effect, and verify
`SHOW max_locks_per_transaction` plus no pending restart before using an empty
isolated recovery target. The recovery command does not reconfigure a user's DB
or weaken its single-transaction restore. Record the effective configuration and
measured resource use with the recovery forecast and readiness evidence.

For target config, retain bundle/extension fields, set new `label`, external DSN
and S3 environment variable names, and set `destination_artifacts` to a new path.
Run `... restore_check.py restore --config TARGET.json --run-id UUID`.
The command verifies all bundle artifact hashes and the exact runtime/platform,
restores PostgreSQL and S3 bytes plus environment artifacts, compares every
catalog/control table and object hash, then replays **every** saved fixture run.
Missing versions/objects, ordering/result differences or wrong environment fail.
A conditional object PUT retry may encounter its own unacknowledged success;
only an existing object whose retained bytes match the exact manifest hash is
accepted. A different payload fails, and occupied-target preflight remains strict.
Retain the JSON report and bundle manifest hash. A failed restore leaves its
isolated target for diagnosis; discard only that task-owned project before
retrying with fresh empty volumes. It does not repair or mutate source stores.

## Publication rollback

With both old and new ingestion/maintenance stopped, call
`rollback_publication(PostgresEndpoint, scope, publication_key, ...)` with the
expected current publication UUID and the exact previous publication UUID,
retained lake, fresh receipt path and failure reason. The target must have an
actual publication under the same authoritative workspace, entitlement and job
publication key, an unreleased permanent hold, and retained catalog versions.
The administrative transaction locks the head and performs a compare-and-swap;
a changed head is a hard failure. Only the publication head changes. Bronze,
identity mappings, accepted generation/outbox/tick receipts, publication history
and all protected holds remain retained.

The CLI `rollback` action additionally requires `--writers-stopped` and config
fields `catalogs`, `scope`, `publication_key`, `expected_publication_id`,
`restore_publication_id`, `receipt_path` and `reason`. Verify the selected old
protected result before resuming the single reviewed ingestion owner. The disk
receipt is `prepared` before the DB change and `committed` after acknowledgement.
If interrupted between DB commit and receipt update, inspect the actual scoped
head to reconcile the prepared receipt. Never assume a prepared receipt means
no change, and never force a retry past a failed expected-head comparison.

The exact head rollback is a service pointer operation; it is not a downgrade of
schema migrations, a deletion of new captures or an automatic Docker traffic
rollback. Keep this rehearsal distinct from Task 14's final live cutover gates
listed in [MIGRATION.md](MIGRATION.md).

## Standalone TemporalDB 0.5.0 integration

The current runtime pin is [temporaldb.lock.json](temporaldb.lock.json). It binds
standalone source, version, Linux arm64 image configuration ID, exported Docker
artifact SHA256 and reviewed provider heads. This is a **local loadable artifact**;
no registry digest has been published or made pullable. Obtain the exact
`temporaldb-0.5.0-linux-arm64.docker.tar` and its provenance from the standalone P
build output, verify the SHA256 in the lock, `docker load -i ARTIFACT`, then check
`docker image inspect IMAGE_ID`. `pull_policy: never` deliberately fails when the
verified local image has not been loaded. amd64 requires its own qualified build.

To rebuild the pinned image instead, check out the lock's `source_commit` in the
temporalDB-docker repository and run its release build. It builds, saves and verifies
the image locally; nothing is pushed, and GHCR images stay private:

```sh
git -C "$TEMPORALDB_SRC" switch --detach "$(python3 -c "import json;print(json.load(open('v11/temporaldb.lock.json'))['source_commit'])")"
(cd "$TEMPORALDB_SRC" && python3 scripts/build_release.py --output /tmp/temporaldb-build --platform linux/arm64)
docker image inspect IMAGE_ID --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'   # must equal source_commit
```

The build writes `provenance.json` beside the artifact; its `image_id`, `artifact_sha256`
and labels are what the lock records. A rebuild is not guaranteed to reproduce the same
image ID; when it differs, re-pin the lock and both compose files from the new provenance.
TemporalDB 0.5.0 adds the `temporaldb_explorer` widget and seeds the v11 example
dashboard's two queries into a workspace when that workspace first asks for `/apps.json`.

Use [compose.temporaldb.yaml](compose.temporaldb.yaml) as an explicit additive v11
profile; the existing v10 stack and gateway policy are unchanged. P owns all
Python/runtime code, build and schema migrations. H contains only integration
configuration and this independent pin. Set separate `TEMPORALDB_API_ENV_FILE`
and `TEMPORALDB_WORKER_ENV_FILE` and `TEMPORALDB_ARCHIVE_HOST`; each service file
contains only its own least-privilege control DSN. Follow P `docs/runtime.md` to
provision the shared archive and schemas before starting replicas. Provision
first-time catalog tables once with `python -m temporaldb.provision catalogs`.

The three one-off steps, in order, as `docker run` forms. `TEMPORALDB_IMAGE` is
the `image_id` in the lock. Add `--network <compose project>_default` when
PostgreSQL and S3 run as Compose services on this host. The archive directory
must be writable by UID 65532 for step 2 only; every later mount is read-only.

```sh
TEMPORALDB_IMAGE=$(python3 -c "import json;print(json.load(open('v11/temporaldb.lock.json'))['image_id'])")
# 1. Migrations (admin DSN in TEMPORALDB_MIGRATION_DSN)
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,size=16777216,mode=1777 \
  --env-file "$TEMPORALDB_MIGRATION_ENV_FILE" \
  "$TEMPORALDB_IMAGE" python -m temporaldb.control.db
# 2. Runtime archive; record the printed environment_digest in both env files
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777 \
  --tmpfs /run/temporaldb/runtime:rw,exec,nosuid,nodev,size=2147483648,mode=1777 \
  -v "$TEMPORALDB_ARCHIVE_HOST":/archive:rw \
  -e TEMPORALDB_IDENTITIES="$(cat identities.json)" \
  "$TEMPORALDB_IMAGE" python -m temporaldb.provision archive --directory /archive
# 3. First-time DuckLake catalogs, once, with the worker environment
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777 \
  --tmpfs /run/temporaldb/runtime:rw,exec,nosuid,nodev,size=2147483648,mode=1777 \
  --tmpfs /run/temporaldb/gold:rw,noexec,nosuid,nodev,size=1073741824,uid=65532,gid=65532,mode=0700 \
  -v "$TEMPORALDB_ARCHIVE_HOST":/archive:ro -v "$TEMPORALDB_EVIDENCE_HOST":/evidence:ro \
  -e TEMPORALDB_EVIDENCE_ARCHIVE=/evidence -e TEMPORALDB_GOLD_SCRATCH_DIRECTORY=/run/temporaldb/gold \
  --env-file "$TEMPORALDB_WORKER_ENV_FILE" \
  "$TEMPORALDB_IMAGE" python -m temporaldb.provision catalogs
```

The retained runtime archive is required, content-addressed and mounted read-only.
Provision a separate durable evidence directory with `blobs/` owned by UID/GID
65532:65532 and mode 0750, and set `TEMPORALDB_EVIDENCE_HOST` to its host path.
The API mounts evidence read-write for audit protection; replay workers mount it
read-only. Preserve both namespaces in backups. New blobs are fsynced and
atomically published without overwriting existing digest names. After stopping all
evidence writers, abandoned `.pending-*` files may be removed; corrupt existing
digest files must be investigated and restored from verified backup, never silently replaced.
Retained Python and native dependencies execute in bounded dedicated
`/run/temporaldb/runtime` tmpfs (`exec,nosuid,nodev`, 2 GiB); `/tmp` stays noexec
(64 MiB). The archive binds Linux OS, architecture and kernel release. Preserve
the exact image and matching platform for recovery; native macOS evidence is a
separate boundary. This local fixture qualification is not NAS/deployment health.

Gold selection uses a separate private `/run/temporaldb/gold` tmpfs, mounted
`noexec,nosuid,nodev`, owned by UID/GID 65532 with mode 0700. Its default aggregate
quota is 1 GiB per active API/worker container (`TEMPORALDB_GOLD_SCRATCH_BYTES`).
Set `TEMPORALDB_GOLD_SCRATCH_DIRECTORY` to that directory. `TEMPORALDB_GOLD_SCRATCH_LIMIT_BYTES` defaults to 805306368
(768 MiB): it caps each DuckDB engine's temporary spill files. Source and Gold
selection each use a separate DuckDB engine with 256 MB memory and one thread;
Arrow/control batches contain at most 2048 rows. A build can have both engines
active, and concurrent builds share the filesystem quota. Per-engine limits do
not guarantee aggregate fit; budget up to 512 MB engine memory per active build.

This scratch is ephemeral selection work, never accepted output, audit evidence,
or executable staging. Completion and exceptions remove process-owned scratch;
a container restart discards its tmpfs, including remnants of a killed process.
An invalid/unwritable directory or filesystem smaller than its configured cap
prevents startup; capacity exhaustion fails the job without publishing Gold. Preserve the
ordinary 64 MiB `/tmp` and separate executable runtime staging. For larger
histories or concurrent work, provision a larger private local-disk mount at the
same path (replace the Compose tmpfs entry), retain its permissions and noexec
mount options, and configure finite engine/filesystem budgets together. Never
point scratch at an archive or evidence mount. Tmpfs usage consumes container/
host memory up to its quota; allow 1 GiB per concurrently active container plus
engine memory and executable staging, or size local disk explicitly.

Gold uses the already pinned DuckDB engine for temporary selection. PostgreSQL
retains immutable selection authority; DuckLake retains accepted data. Scratch
contains no durable Gold output and does not require another processing engine.
There is no permanent dataset row cap. Row widths, action/retrieval lineage and
concurrent builds change space demand; measure representative workloads before
increasing capacity. Public query limits remain 100000 rows, 64 MiB and the
absolute execution deadline. Final-artifact qualification is a separate release
gate from source-mounted diagnostics.


Recovery inventory additionally includes Q3 audit rows, original execution
receipts and Arrow result objects, their full accepted normalization/Gold/tick
input closure, every protected hold, and **all referenced native archive blobs**.
Include original/replay environment digest, lock/provenance and independently
managed secrets with the stopped-writer backup procedure above. Replay verifies
retained typed results; restoring a catalog alone is insufficient. No migration
rollback, shared prune, provider acquisition or traffic cutover is performed.

The production worker coordinates accepted managed refreshes into receipt-gated
Gold automatically. Recorded-fixture linked UI/two-API/two-worker/restore and
Linux artifact qualification are recorded in the final release evidence. Packaged
native restart, actual NAS loads and cutover remain separate gates.

## Tailnet names (Tailscale Services)

The desktop app and Rita's MCP calls reach TemporalDB over the tailnet through two
Tailscale Services. `ts-config/serve-v11.json` is `serve-v6-services.json` (Episode 6's
opt-in `svc:openbq-keys`, `svc:openbq-rita` and `svc:openbq-mcp`; see the README) plus:

| Service | Name | Proxies to |
|---|---|---|
| `svc:openbq-temporal` | `https://openbq-temporal.<your-tailnet>.ts.net` | `temporaldb-api:8080` |
| `svc:openbq-temporal-mcp` | `https://openbq-temporal-mcp.<your-tailnet>.ts.net/mcp` | `temporaldb-mcp:8081` |

1. Create all five Services in your tailnet's admin console and approve the stack's
   `openbq` node as their host. Until they exist, keep the v6 serve file. The
   `:10443` (Rita) and `:11443` (MCP) ports keep working alongside them.
2. Replace `<your-tailnet>` in `ts-config/serve-v11.json` (tailnet-only, never funneled).
3. Add `-f v11/compose.tailnet.yaml` after the other v11 files. It points the
   sidecar at `serve-v11.json` and keeps `temporaldb-api` on `openbq-internal`.
4. Set `TEMPORALDB_MCP_ALLOWED_HOSTS` to `["openbq-temporal-mcp.<your-tailnet>.ts.net"]`.
   Confirm with one MCP Check from the app: a Host mismatch is refused, and the
   value Serve forwards has not been verified on a live tailnet yet.

In BDOBB, add `https://openbq-temporal.<your-tailnet>.ts.net` as a connection with
its scope token, and the MCP URL under **AI Library ▸ MCP Servers** with its MCP token.
The MCP Service answers 502 until the `mcp` profile runs.

## Opt-in v11 TemporalDB gateway

Canonical `funnel-gateway/policy.mjs` stays byte-for-byte v10. The separate
`funnel-gateway/temporal-policy.mjs` is the exact v11 route/method contract;
C vendors its bytes under a separate source-commit/hash receipt. To configure
this path, combine `docker-compose.yml`, `v11/compose.temporaldb.yaml` and
`v11/compose.gateway.yaml`, with profiles `web` and `temporaldb-v11`. The last
overlay places both `temporaldb-api` and `openbq-v11` on the gateway's
`openbq-internal` network and builds a separately named gateway image.
For `/api` provider requests, set `"apiUpstream": "v11"` in settings.json.
Only `"v10"` (the default, `http://openbq-api:6900`) and `"v11"`
(`http://openbq-v11:6900`) are accepted. The gateway never retries a failed v11
request against v10. Arbitrary URLs and per-request upstream selection are refused.
The gateway's OPENBB_API_USERNAME/OPENBB_API_PASSWORD must match the Basic pair
in the private v11 provider environment.
The exact GET `/api/widgets.json` response has an 8 MiB limit when v11 is
selected, accommodating the installed provider catalogue. V10 and every other
response retain the 2 MiB limit. Declared and streamed bytes are bounded;
compressed responses are refused. Request, time and concurrency limits remain
unchanged.

`"temporalDB": true` independently enables the `/temporal` query routes below.
It does not select the provider host for `/api`. Selecting `apiUpstream:v11`
does not require enabling `/temporal`. Standalone base + temporaldb overlay
keeps provider/capture on the default network; the three-file combination joins
both to the gateway network. Existing v10 defaults and policy remain unchanged.

After loading the pinned images and provisioning the durable stores/archive,
export the absolute private `TEMPORALDB_API_ENV_FILE`,
`TEMPORALDB_WORKER_ENV_FILE`, `OPENBQ_V11_ENV_FILE`, `TEMPORALDB_ARCHIVE_HOST`,
`TEMPORALDB_EVIDENCE_HOST` and immutable `OPENBQ_V11_IMAGE` values described above.
From the repository root, render and start the explicit provider path:

```sh
docker compose -f docker-compose.yml -f v11/compose.temporaldb.yaml \
  -f v11/compose.gateway.yaml --profile web --profile temporaldb-v11 \
  config --no-env-resolution
docker compose -f docker-compose.yml -f v11/compose.temporaldb.yaml \
  -f v11/compose.gateway.yaml --profile web --profile temporaldb-v11 \
  build funnel-gateway
docker compose -f docker-compose.yml -f v11/compose.temporaldb.yaml \
  -f v11/compose.gateway.yaml --profile web --profile temporaldb-v11 \
  up -d --no-deps temporaldb-api temporaldb-worker openbq-v11 funnel-gateway
```

The explicit service list and `--no-deps` avoid starting the legacy API solely
because the base gateway declares it as a dependency. Set settings and private
gateway.env before startup; this command assumes the deployment's existing
network ingress is already configured. Review rendered configuration locally;
it can include private environment values.

Add `TEMPORALDB_GATEWAY_TOKEN` to private `gateway.env` (32–256 base64url
characters, distinct from GATEWAY_TOKEN). That token must map to the intended
shared workspace/entitlement/principal in P's `TEMPORALDB_SCOPE_POLICY`. The
fixed upstream is `http://temporaldb-api:8080`; settings and requests cannot
supply another upstream URL. This deployment intentionally grants authorized
preview users the same configured TemporalDB service scope, not separate
per-GitHub-user TemporalDB principals. Use a dedicated deployment for each
scope. Keep API/worker DSNs and all credentials server-side.

C must separately set `TEMPORALDB_V11=true` alongside its existing authenticated
BACKEND_GATEWAY_ORIGIN/TOKEN. Its bootstrap offers backend base URL
`https://PREVIEW/temporal`. For that base, discovery is `/temporal/`,
`/temporal/widgets.json`, `/temporal/apps.json`; API calls are
`/temporal/temporal/v1/...`. The gateway strips exactly the first `/temporal`.
The repeated segment is the existing backend-prefix convention, not an alias.

The overlay admits capabilities and reviewed query library, execution/page/cancel
and protected audit/replay routes only, with exact methods/UUIDs/query bounds.
No captures, health/admin, arbitrary targets, wildcard paths or sockets are
added. Both proxies authenticate before route disclosure; web writes also need
same-origin CSRF checks. Bodies are JSON up to 1 MiB; responses up to 2 MiB;
upstream timeout 12 seconds; existing request/concurrency limits apply. Browser
credentials are discarded; C injects the gateway token, H injects only the
separate TemporalDB token. Redirects, cookies, auth challenges and error bodies
are never forwarded. Known semantic status codes survive; upstream 401 becomes
502 so it cannot masquerade as a lapsed browser session.

The P `tests/test_gateway_browser.py` opt-in harness exercises real Chromium,
actual C discovery/client/platform fetch, C web relay, H gateway and P configured
API/worker with disposable recorded fixtures. It is transport qualification,
not full application UI, live provider, NAS, public Funnel or deployment proof.


## Final acceptance and cutover gate

Standalone runtime 0.3.1 contains managed daily/actions/fundamentals/FRED/tick
Gold coordination and migration PASS authority. Apply immutable migrations through
015 before using it. Migration capture ownership is reserved before acquisition;
only the exact persisted normalization/reference PASS authorizes Gold. New tick
Gold views freeze authorized generations, so pending/failed migration revisions
cannot enter through a later ordinary refresh. Existing published definitions
keep their recorded semantics; unclassified legacy tick captures/queued Gold
fail closed for new promotion. Ordinary accepted observations remain managed.
The final immutable local image, exact source commit, Docker-save SHA256 and
reviewed E/Y provider heads are in `temporaldb.lock.json`. Load and verify that
artifact first; it is unpublished and `pull_policy: never` is intentional.
The old 0.2.0 and 0.3.0 artifacts remain historical; their qualification does not
establish the new authority fix. P retains their source/artifact receipts.

Run P `scripts/accept_v11.py` with C/H checkout paths after building C's full
browser bundle as documented in P/C release acceptance notes. This uses recorded
captures, actual configured API/worker services and the real authenticated
C→gateway→TemporalDB route. The optional `compose.acceptance.yaml` adds a second
API and worker to a separately named fixture-only Compose project. It is not a
request to start replicas against deployed stores. The harness itself manages
bounded tmpfs PostgreSQL/S3 and an independent recovery target.

The exact recovery set includes the full PostgreSQL custom dump (control authority,
query revisions/executions, audits/replays, capture/outbox and normalization
receipts, tick migration/range/reference receipts, publications/holds/retirement,
`gold_refreshes`, `managed_gold_inputs`, `tick_capture_owners`,
`tick_gold_authorizations`, `tick_legacy_captures`, exact reconciliation reference
lineage/holds, and DuckLake metadata including inlined
rows), every named S3 bucket object and hash, exact extension/lock artifacts,
and the complete retained interpreter/application/native-dependency archive.
Provision role memberships and credentials separately. Stop all writers and
maintenance across both stores before taking the inventory; do not infer a
cross-store atomic backup from a database snapshot alone.

Before any later cutover, separately qualify live acquisition coverage, scoped
credentials, actual NAS throughput/capacity and shared durability, public OAuth,
and the packaged native lifecycle. Record calibration's acquired and missing
coverage, request/byte/cost bounds and explicit unknowns. Gate traffic promotion
on independent restore and whole-branch review, then maintain the prior image,
source and recovery inventory for rollback. Rollback is administrative CAS on
an exact retained publication plus its receipt, not an unchecked head rewrite.
No deployment, cutover, registry publication or live/NAS load was performed here.

## Recorded release receipts (2026-10-15)

The historical local 0.3.1 artifact is built from standalone P
`b0484c562e7be747eec3614d2186d72cd83f9162`; its immutable image/configuration ID,
Docker-save SHA256, lock hashes and reviewed provider commits are retained in
`temporaldb.lock.json`. `temporaldb-qualification.json` records actual Linux arm64
API/worker startup, migration015, managed ticks/FRED, exact migration PASS and
FAIL boundaries, exclusion of failed migration revisions from a later ordinary
refresh, immutable prior Gold, and archived replay. Retained native imports
and `/proc/self/maps` libpython loading were also verified from the archive.

Supported Linux Node 22 gateway tests passed 91/91. H gateway implementation is
still `8104edd50c57c602278baaf1b7189fa204d45074`, matching C's separate v11 vendoring
receipt. Canonical v10 policy and its C receipt remain unchanged. The final
profile-enabled fixture Compose configuration validates four API/worker service
definitions against the new immutable image; this does not start a deployment.

The prior complete full C app/gateway acceptance passed, with 28 requests handled by each
API factory, two configured worker processes, linked chart/export provenance and
independent recovery of both protected UI and tick executions. Recovery matched
71 tables, 99 objects, 11 managed refresh rows and 2 frozen managed FRED inputs;
administrative rollback was committed. The complete command/results/limitations
summary and compact receipts are in P `docs/releases/v11/final-validation.md`.
The changed P source additionally passed 86 focused tests, including actual
Gold-backed execution, protection, cleanup, archived replay and both independent
restore paths with populated authority/selection records at explicit 1GiB/512
fixture capacity. The earlier full P capacity failures remain documented; no
third full P run or repeated full C gate is claimed. Do not infer live/NAS/public
OAuth/packaged native qualification from these fixtures.

The v11 provider host is a separate `openbq-v11` service. `Dockerfile` remains the
legacy recipe. `v11/Dockerfile.providers` replaces both provider distributions
with the reviewed commits in `temporaldb.lock.json`. Prepare clean clones at those
commits, then run:

```sh
python3 v11/prepare-provider-build.py --eodhd ../openbq-eodhd-v11 --yfinance ../openbq-yfinance-v11 --build
```

The script refuses dirty or mismatched checkouts, archives the exact Git commits,
and passes their SHA256 values to the build, which verifies each archive before
installation. Build tools and yfinance come only from the hash-locked
`v11/providers.lock` (`uv pip compile v11/providers.in -c requirements.lock
--universal --python-version 3.12 --generate-hashes -o v11/providers.lock`).
`v11/build-inputs/sources.json` records the actual inputs. Local
archives do not assert that unpublished commits can be fetched remotely; after
publication operators may fetch those exact commits into clean clones and run the
same command. Use the resulting immutable image ID as `OPENBQ_V11_IMAGE`.
`OPENBQ_V11_ENV_FILE` must provide each provider's `*_CAPTURE_TOKEN`,
`*_CAPTURE_WORKSPACE_ID`, `*_CAPTURE_ENTITLEMENT`, `*_CAPTURE_PRINCIPAL`, and `*_CAPTURE_ACCOUNT`, matching
P's server-side token policy and its `provider_accounts` mapping. EODHD uses the
host's configured `EODHD_API_KEY`; foreign per-call keys are rejected. Yahoo uses
an explicit public-account identifier. Provider keys stay in the private host environment.
The overlay mandates capture and uses the private compose API service; missing
coordination or durable acknowledgement prevents fresh provider data from returning.

## Current candidate qualification

The current local TemporalDB 0.4.0 Linux arm64 image is built from executable source
`b769205ac1a5d1bf4280433beb944966cdc75498`, image
`sha256:fa9ed15f19b69f3cb8058753bfdcfcc989e747d94cfb2702a0b139da1ccf3770`.
The exact Docker-save SHA256 is in `temporaldb.lock.json`; current gate results are
in `temporaldb-wholebranch-fix-qualification.json`. Later evidence commits are not image
source. Load and verify this exact unpublished artifact before provisioning.

The new installed combined gate passed1 pytest/528.69s and1 Chromium/28.4s. It
covers actual2API/2worker mount policy, configured split-store service bundling,
filtered Gold/Silver over100001 accepted current/history rows and independent UI
protected-run restore (94 tables/241 objects). The isolated bulk fixture has its
own genuine scale-1 archive; its four protected runs have exact replay evidence,
not individual independent restore claims. The main environment is
`3cabfeb63fd23afe921ff79b41f81d85d702e4b4f5be6f1458e252d4d177813b`;
the bulk fixture environment is
`fd57b647f46719c4cc8bbb54840109416ffe7716a20463eb14b0a27ec8fae0f8`.
Main workers stop before the bulk controller phase.

The new RO-archive ordinary gate passed current/snapshot/protect/replay and a
small genuine accepted tick/protect/replay; the narrow installed-wheel Arrow/Polars
bridge passed2 tests. Shared RW evidence in the ordinary diagnostic does not replace
the combined gate's API-RW/worker-RO proof. Attempt01's pnpm prerequisite failure
is retained separately from the successful explicit Node22/pnpm10.34.4 retry.

The original725-node baseline has712 nodes with passing evidence,11 skips,1 local
mount unavailable and1 stale HTTP200-empty-array negative. A later focused group
passes the corrected null negative and legitimate empty windows. The prior actual
Linux native mount is reused. Task6 closing review approved those old-source
baseline dispositions; scoped final fix review is still pending. Unchanged
provider/settings/Workspace/session/native-analysis evidence retains original
source/image identities with byte/dependency comparisons, not new-image claims.
See P's `docs/releases/v11/final-fix-qualification.md` for current proof and limits.
No release, registry push, merge, deployment or cutover is authorized.

### Historical Task6 candidate qualification

The historical TemporalDB 0.4.0 Linux arm64 image was built from clean executable source
`75d5389d0b68a7041b84e7e7e1f04d097d8ff9b1`. The exact local image and Docker-save
SHA256 are retained in `temporaldb-task6-qualification.json`, which records
the gate status at that time. Later harness/documentation commits are not the image source.
The archive is unpublished. Load and verify that exact artifact before provisioning.

The final installed provider topology passed two tests with the requested image
asserted in rendered API/provision configuration and actual running API image/source.
The provider host remains the independently verified66a498 artifact with unchanged
E/Y source pins. Recorded EODHD HTTPS and Yahoo SDK retrievals exercise real capture
coordination, account policy and durable acknowledgement; no live paid calls occur.

The final combined fixture ran two actual API containers and two worker containers
from the exact image. It exercised default multisource concurrent Gold, shared query
revision, table/chart/export, protected Arrow publication, actual foreign-workspace
and foreign-entitlement route denials, and separate-store protected replay through
the retained Linux query runtime. All94 tables/38 objects matched. Publication
negative cases left the whole registry and both owned bucket inventories unchanged.
The separately labeled disabled-publication API only serves the negative phase.

API evidence mounts were RW, worker evidence mounts RO and all runtime archives RO.
The fixture uses a byte/mode-verified private Linux volume to qualify Linux filesystem
semantics. Operators still supply durable shared storage as described above. This
fixture establishes neither macOS Docker bind/NAS latency nor power-loss durability.
The targeted ordinary child-process diagnostic uses shared RW evidence and is not
the evidence for shipped role-specific mounts.

Complete split-session migration now has real worker owner-loss, failed-session and
100,001-tick acceptance/canonical proof under the original1800s bound. Historical
partial-session/0.3.2 gaps above do not describe current implementation. The first
final full runtime run passed its tick phases but later hit a snapshot execution
deadline; its failed result remains recorded alongside targeted follow-up evidence.
Consult P's `docs/releases/v11/task6-qualification.md` for the final aggregate,
remaining baseline failures/skips and review status. Local qualification does not
authorize registry publication, live acquisition, public networking or deployment.

### Optional shared OpenBQ settings

[Settings provisioning and migration](settings/README.md) describes the separate
PostgreSQL settings database, stable key principal and explicit legacy-copy
import/reverse export. Append `v11/compose.settings.yaml` after the existing v11
gateway overlay and select gateway `stateStorage: "postgresql"` with
`apiUpstream: "v11"`. Runtime and migration env files are separate. This opt-in
path does not migrate official Workspace relational data or authorize a cutover.
