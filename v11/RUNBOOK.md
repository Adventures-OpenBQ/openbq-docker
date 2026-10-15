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

## Standalone TemporalDB 0.3.0 integration

The current runtime pin is [temporaldb.lock.json](temporaldb.lock.json). It binds
standalone source, version, Linux arm64 image configuration ID, exported Docker
artifact SHA256 and reviewed provider heads. This is a **local loadable artifact**;
no registry digest has been published or made pullable. Obtain the exact
`temporaldb-0.3.0-linux-arm64.docker.tar` and its provenance from the standalone P
build output, verify the SHA256 in the lock, `docker load -i ARTIFACT`, then check
`docker image inspect IMAGE_ID`. `pull_policy: never` deliberately fails when the
verified local image has not been loaded. amd64 requires its own qualified build.

Use [compose.temporaldb.yaml](compose.temporaldb.yaml) as an explicit additive v11
profile; the existing v10 stack and gateway policy are unchanged. P owns all
Python/runtime code, build and schema migrations. H contains only integration
configuration and this independent pin. Set separate `TEMPORALDB_API_ENV_FILE`
and `TEMPORALDB_WORKER_ENV_FILE` and `TEMPORALDB_ARCHIVE_HOST`; each service file
contains only its own least-privilege control DSN. Follow P `docs/runtime.md` to
provision the shared archive and schemas before starting replicas. Provision
first-time catalog tables once with `python -m temporaldb.provision catalogs`.

The shared archive is required, content-addressed and read-only at runtime.
Retained Python and native dependencies execute in bounded dedicated
`/run/temporaldb/runtime` tmpfs (`exec,nosuid,nodev`, 2 GiB); `/tmp` stays noexec
(64 MiB). The archive binds Linux OS, architecture and kernel release. Preserve
the exact image and matching platform for recovery; native macOS evidence is a
separate boundary. This local fixture qualification is not NAS/deployment health.

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

## Opt-in v11 TemporalDB gateway

Canonical `funnel-gateway/policy.mjs` stays byte-for-byte v10. The separate
`funnel-gateway/temporal-policy.mjs` is the exact v11 route/method contract;
C vendors its bytes under a separate source-commit/hash receipt. To configure
this path, combine `docker-compose.yml`, `v11/compose.temporaldb.yaml` and
`v11/compose.gateway.yaml`, with profiles `web` and `temporaldb-v11`. The last
overlay places `temporaldb-api` on the gateway's `openbq-internal` network and
builds a separately named gateway image. No traffic is enabled by the network
alone: settings.json must explicitly contain `"temporalDB": true`.

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

Standalone runtime 0.3.0 contains managed daily/actions/fundamentals/FRED/tick
Gold coordination. Apply immutable migrations through 014 before using it.
The final immutable local image, exact source commit, Docker-save SHA256 and
reviewed E/Y provider heads are in `temporaldb.lock.json`. Load and verify that
artifact first; it is unpublished and `pull_policy: never` is intentional.
The old 0.2.0 qualification remains historical, not proof of the final coordinator.

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
`gold_refreshes`, `managed_gold_inputs`, and DuckLake metadata including inlined
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

The final local 0.3.0 artifact is built from standalone P
`7a238d843fc19885d41a590a7af2bf2e3e3a6a27`; its immutable image/configuration ID,
Docker-save SHA256, lock hashes and reviewed provider commits are retained in
`temporaldb.lock.json`. `temporaldb-qualification.json` records actual Linux arm64
API/worker startup, migration014, three managed Gold refreshes (including ticks
and FRED), a frozen FRED selection and archived replay. Retained native imports
and `/proc/self/maps` libpython loading were also verified from the archive.

Supported Linux Node22 gateway tests passed 91/91. H gateway implementation is
still `8104edd50c57c602278baaf1b7189fa204d45074`, matching C's separate v11 vendoring
receipt. Canonical v10 policy and its C receipt remain unchanged. The final
profile-enabled fixture Compose configuration validates four API/worker service
definitions against the new immutable image; this does not start a deployment.

The actual full C app/gateway acceptance passed, with 28 requests handled by each
API factory, two configured worker processes, linked chart/export provenance and
independent recovery of both protected UI and tick executions. Recovery matched
71 tables, 99 objects, 11 managed refresh rows and 2 frozen managed FRED inputs;
administrative rollback was committed. The complete command/results/limitations
summary and compact receipts are in P `docs/releases/v11/final-validation.md`.
Do not infer live/NAS/public OAuth/packaged native qualification from these fixtures.
