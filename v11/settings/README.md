# OpenBQ shared settings (v11 opt-in)

This package stores the existing key-mode settings/dashboard/app documents and the
browser gateway's `/state` files in a separate PostgreSQL application database.
It never connects to TemporalDB's control/catalog database. Workspace relational
migration is separate. The default remains the existing JSON-file backend.

The v11 appended Docker stage installs `openbq_settings.py`, this package as
`openbq_settings_pg`, pinned psycopg 3.3.2/pool 3.3.0, and a TOML containing both
settings and lanes hooks. The root/v3 Dockerfiles, lanes TOML and base dependency
lock remain untouched. `python -m openbq_settings_pg.launch` uses the installed
ODP 2.0.1 launcher and normal app; its lifespan verifies the store before listen
and closes its pool at shutdown. Run one worker per container; multiple replicas
share the database. Reload/multiworker flags are refused in selected PG mode.
`WEB_CONCURRENCY` must be absent or exactly `1`; explicit `--workers 1` is accepted.

## Provision and select

Use an administrator connection to run `provision.sql` once on the retained
server. Supply `OPENBQ_SETTINGS_RUNTIME_PASSWORD` and
`OPENBQ_SETTINGS_MIGRATION_PASSWORD` through a protected environment file.
Database name is the explicit psql `settings_database` variable. Roles are fixed:
nonlogin `openbq_settings_owner`, login `openbq_settings_migrator`, and login
`openbq_settings_runtime`. Runtime has document DML but no schema CREATE,
owner membership, checkpoint writes, superuser or cluster administration rights.
The newly provisioned database revokes PUBLIC access. Provision other application
databases with equivalent separate CONNECT grants; do not grant their roles here.

```sh
psql -X -v ON_ERROR_STOP=1 -v settings_database=openbq_settings -f provision.sql
python -m openbq_settings_pg.migrate_json migrate
```

The migration command reads only `OPENBQ_SETTINGS_MIGRATION_DSN`. Give that secret
only to the explicit migration/import job. It obtains the settings advisory lock,
runs `settings-001`, and records the SHA256 of `schema.sql`. Repeated migration
checks the exact revision/checksum; an unknown version or checksum fails closed.
Runtime never applies DDL. DSNs are libpq strings or correctly encoded PostgreSQL
URIs; no tool concatenates passwords into URLs. Require explicit host, database,
user and `connect_timeout` (1–10 seconds). TLS fields pass directly to libpq;
use `sslmode=verify-full sslrootcert=/private/ca.crt` for verified remote TLS
(`sslrootcert` without `sslmode` defaults to `verify-full`, otherwise `require`).
Ambient `PG*` variables are refused, preventing unintended inherited targets.
Routine errors and pool retry logs never print DSNs or document contents.

Runtime private env file:

- `OPENBQ_SETTINGS_BACKEND=postgresql` (unknown or empty values refuse startup).
- `OPENBQ_SETTINGS_DSN` for the runtime role, never an admin/migration credential.
- `OPENBQ_SETTINGS_PRINCIPAL_ID`: canonical stable UUID, retained during Basic
  password rotation and identical on replicas serving the same key-mode account.
- `OPENBQ_SETTINGS_GATEWAY_STATE=1` and the existing `GATEWAY_TOKEN` to enable the
  private browser-state route. This token is separate from TemporalDB's token.
- The existing `OPENBB_API_AUTH`, username and password continue to protect key
  routes. Do not replace them with the machine token.

Append `v11/compose.settings.yaml` after the temporaldb and gateway overlays.
`OPENBQ_SETTINGS_ENV_FILE` appends to the existing provider env-file list.
`OPENBQ_SETTINGS_MIGRATION_ENV_FILE` belongs only to the `settings-migrate`
profile. The overlay neither starts nor publicly exposes PostgreSQL. Supply
network reachability to the separately provisioned server. Gateway settings JSON
selects `"stateStorage":"postgresql"` and `"apiUpstream":"v11"`; remove
`stateDir` for that selection. Keep credentials in the existing gateway.env.
Gateway receives no PostgreSQL DSN and has no arbitrary-origin option or fallback.

## Semantics and bounded resources

Basic auth resolves to the explicit key UUID. Browser numeric IDs remain strings,
including leading zeroes, in the distinct `github` namespace. Only the existing
machine Bearer can use `/_openbq/settings/v1/state/<id>[/<allowlisted-name>]`.
That route is excluded from ordinary proxy policy. Key-mode request, root-folder,
per-item dashboard/app, hidden docks, revision and last-write-wins behavior stays
compatible. Key settings/dashboard/app writes use the established JSON serializer
and preserve unknown content keys. Browser bytes are retained unchanged as BYTEA.

Each mutation creates/locks the principal row before checking totals or reading
and changing documents. This also serializes first writes to different files
across processes. Browser quotas remain 262144 bytes/file, 2097152 bytes/user and
200 files/user. Key-mode stored dashboard/app aggregates can exceed a single
5000000-byte request. Internal database revision overflow refuses the transaction;
client docks revisions retain their existing independent JSON integer behavior.

Per API process: pool maximum 2, no overflow, at most 10 admitted worker operations
(two active); ten-second wait, eight-second statements, five-second row-lock
wait, ten-second idle transaction timeout. Synchronous transactions run off the
ASGI event loop. Cancellation waits for transaction completion before releasing
worker capacity. Two replicas budget four runtime connections; explicit migration
or import jobs each add one. Do not change cluster connection/lock settings here.
The healthcheck reads the selected settings endpoint, so DB failure cannot report
healthy merely because widgets are cached.

Only the state-list read budget changes: H private transport and C savedState use
`6 * 2097152 + 200 * (96 + 6) + 11 = 12603323` bytes. This covers JSON escaping,
UTF-8 replacement, names and envelope. Reject an oversized declared length before
buffering and independently bound the stream. No partial response enables browser
persistence. Ordinary 2 MiB and exact-v11-widgets 8 MiB budgets stay separate.

## Explicit import and new-generation reverse export

Stop all writers and use a consistent **copy**. The source layout is explicit:
`source/keys/<64-hex-stem>[.dashboards|.apps].json` and
`source/state/<numeric-id>/<encodeURIComponent(logical-name)>`.
The mapping file is a JSON object from each selected legacy credential stem to a
canonical stable principal UUID. It contains no Basic credentials. Multiple stems
mapping to one UUID are refused: select the authoritative generation explicitly.
Unmapped, malformed, unknown, symlinked, noncanonical encoded or overquota sources
are refused. `--exclude-temp` explicitly excludes only recognized abandoned
legacy temporary names; their source hashes remain in the protected manifest.
Key files must be readable by the legacy UTF-8 text loader: BOM, UTF-16 and UTF-32
key source files are refused. Browser byte validation is unchanged.

```sh
python -m openbq_settings_pg.migrate_json inventory --source /copy/source --mapping /private/map.json --quiesced-copy
python -m openbq_settings_pg.migrate_json import --source /copy/source --mapping /private/map.json --quiesced-copy
python -m openbq_settings_pg.migrate_json verify --source /copy/source --mapping /private/map.json --quiesced-copy
python -m openbq_settings_pg.migrate_json export-legacy --destination /new-generation/export --mapping /private/destination-map.json --quiesced-copy
```

Import and completion checkpoint commit together. The checkpoint records source
manifest, schema checksum, document lengths/hashes and mapping. An interrupted
transaction leaves no partial usable store. An identical completed import can
verify/no-op; divergent source/target or unrelated populated targets refuse.
After runtime writes, the old import checkpoint intentionally no longer verifies.

Reverse export reads one consistent document snapshot, writes new protected files,
verifies counts/hashes and atomically publishes a new destination generation.
Choose the destination stem explicitly (it may represent a rotated Basic pair).
Never overwrite the original source or treat an old pre-write snapshot as a
rollback including later writes. Restore key files as OPENBQ_SETTINGS_DIR and
browser numeric directories as gateway stateDir. Every later write requires a new
quiesced export. No arbitrary historical schema conversion is provided.
An earlier unreleased PG store may contain non-UTF-8 or BOM key settings. Export
refuses these before publishing a generation; it never converts bytes or rewrites
checkpoints automatically. Explicitly GET the logical settings with the affected
principal's Basic credential, then POST that object through the fixed API before
creating and verifying a new export. Existing checkpoints are not retroactively
made valid. This policy does not authorize modifying live user state.

Separately, run `pg_dump -Fc` with a protected operator connection, provision a
fresh isolated settings-only database/roles, then `pg_restore --exit-on-error`
there. Preserve owner/grant information and schema/checkpoint tables; verify
runtime schema and endpoints before switching a fixture. Do not use `--clean`
against an existing user database. Dumps and env files are sensitive artifacts.

## Verification

`verify-settings.sh /private/task-artifacts` builds reviewed provider archives,
runs the installed real PostgreSQL/TLS/two-API/two-Node22-gateway fixture and the
scoped regressions. It uses only generated state and task-owned Docker resources.
Artifacts include private source/export/dump/env data; publish only aggregate
checks and artifact hashes. No live user compatibility or deployment claim is
made by synthetic fixture success.
