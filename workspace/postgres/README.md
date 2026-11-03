<!-- Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0. -->
# Pinned Workspace PostgreSQL profile

This profile runs official Workspace/Lite at `be00e95019a55d57af146919ee46b7e1a4859226` on a dedicated `openbq_workspace` database on the retained PostgreSQL server. It does not change key-mode settings, TemporalDB, DuckLake, or v10. SQLite is an offline compatibility source and reverse-restore target, not an analytical engine.

## Build the reviewed artifact

Use a clean checkout at the exact pin. Assembly is copy-only; patching is separate:

```sh
workspace/scripts/assemble.sh /path/to/pinned-workspace
workspace/scripts/apply-patches.sh
docker build --platform linux/amd64 --target frontend-build -t workspace-frontend:review workspace/build-context
docker build --platform linux/amd64 -t workspace-postgres:review workspace/build-context
```

An existing assembly/patch marker, modified copied input, different pin, changed original lock, or changed recorded resolved lock fails closed. Preserve a failed context for diagnosis and explicitly move it before fresh assembly. Patches001–005 apply in order before Cython compilation. The runtime contains `workspace-build.json`, including source/patch/tool/manifest hashes. The recorded resolved lock is used without resolution; Python3.13, SQLAlchemy2.0.52, Alembic1.19.1, asyncpg0.31.0 and psycopg2-binary2.9.12 remain pinned. Original build provenance remains in `source.json`.

## Provision, migrate, then import or bootstrap

Provision only a new dedicated database. Its name must match lowercase `[a-z][a-z0-9_]{0,62}`; invalid names fail before catalog changes or connection switching. Supply administrator connection variables and `WORKSPACE_MIGRATOR_PASSWORD`, `WORKSPACE_READ_PASSWORD`, `WORKSPACE_WRITE_PASSWORD` through private environment input to psql; never put credentials in command arguments or tracked files:

```sh
psql -v workspace_db=openbq_workspace -f workspace/postgres/provision.sql
```

The owner is NOLOGIN; the migrator is NOINHERIT and explicitly selects the owner. Runtime read/write roles have no owner membership, DDL, checkpoint writes, or cross-application grants. Runtime reads only the minimal readiness seal. Provisioning does not modify ACLs on existing settings/catalog databases.

The opt-in overlay mounts only the explicitly supplied `OPENBQ_WORKSPACE_TLS_DIR` at `/run/workspace-tls` for migration; it does not mount the runtime key/storage volume into that job. Set SSL_CA and optional SSL_CERT/SSL_KEY paths inside that directory consistently in runtime and maintenance environments. Without SSL_CA or SSL_CERT/SSL_KEY, runtime and migration refuse to connect; only `WORKSPACE_POSTGRES_ALLOW_PLAINTEXT=1` deliberately selects plaintext, and an empty directory is sufficient only then.

Migration-only environment uses the same DB_HOST/PORT/NAME fields, both READ/WRITE credentials set to the migrator, and `WORKSPACE_MIGRATION_ROLE=openbq_workspace_owner`. It needs no runtime identity keys or Redis. With the verified image and private env-file paths set:

```sh
docker compose -f docker-compose.yml -f v11/compose.workspace-postgres.yaml run --rm openbq-workspace-migrate
```

Migration traverses the full existing history to `9b1d0c5e7a42`, under a bounded advisory lock on the same physical connection. Every waiter rechecks the head after acquiring the lock. Partial, drifted, and older PostgreSQL profiles are refused. The PostgreSQL variant of the pin's three-millisecond DATETIME request is promoted to six-digit precision to preserve valid SQLite microseconds; existing PG precision3 stores are not silently altered or accepted. MySQL/SQLite precision behavior is unchanged.

Choose exactly one initialization path:

* **Existing installation:** use the complete offline import below, with original keys, explicit entity/inviter mapping, folder storage and Redis companions. Never bootstrap an imported store.
* **Fresh installation:** explicitly run `openbq-workspace-bootstrap` with a private bootstrap env file containing the migrator identity and administrator inputs. It verifies the complete known seed-only schema before generating keys, creates accounts through pinned upstream logic, validates relationships, and seals readiness. Its child alone selects owner on each connection. After the freshness guard, bootstrap creates `/data/redis`, `/data/storage` and `/data/state`, refuses symlinks or non-directory entries, and sets only those directories and `/data` to the pinned appuser identity. It does not recursively change imported files. Repeated/partial bootstrap is refused; restore a known fresh fixture or approved backup rather than reseeding partial data.

Maintenance jobs are serialized. PostgreSQL defaults to `serve`, including when WORKSPACE_DB_ACTION is absent. `serve` verifies the complete schema, protected mapping, original usable keys and readiness before any listener. It never migrates, creates/promotes accounts, resets passwords, rotates secrets, or repairs historical application rows. Changed bootstrap password variables do not change imported credentials. Explicit restored SQLite must select `WORKSPACE_DB_ACTION=serve`; legacy SQLite without the selector retains upstream startup behavior.

## Complete offline transfer

Work only on a quiesced operator-approved copy. Keep a separate unchanged original and companions. `snapshot` uses SQLite's backup API, including committed WAL pages. All source/output/mapping paths must be regular files under an explicitly supplied private offline root; symlinks, escapes, overlapping source/output, existing destination and unsupported schema are refused. The resolved SQLite export and mapping output paths must differ; overlap is rejected before database work or output publication. No endpoint discovers or imports files opportunistically.

Run the packaged tool in the verified image with the offline directory mounted at `/offline`. Provide `WORKSPACE_TARGET_DSN` only through a private environment file, with a structured psycopg2 URL and no query overrides. Provide the original four identity values and TLS fields in that private input. Do not pass a DSN on the command line. Commands below are the Python portion of that isolated invocation:

```sh
python -m scripts.workspace_migration inventory --root /offline --source /offline/copied.db
python -m scripts.workspace_migration snapshot --root /offline --source /offline/copied.db --output /offline/snapshot.db --quiesced
python -m scripts.workspace_migration import --root /offline --source /offline/snapshot.db --run-id approved-run --mapping /offline/input-map.json --mapping-output /offline/permission-map.json
python -m scripts.workspace_migration verify --root /offline --source /offline/snapshot.db --run-id approved-run
```

The 0600 input mapping contains explicit `entity_uuid` and `inviting_uuid` from reviewed existing relationships. Import validates one matching Admin and User permission, the inviter's Admin relationship, and the pinned trial mapping. It never guesses the first administrator. The protected output mapping binds the original identity material and is copied to `/data/permission-map.json` on each instance. Runtime derives the pinned `user_create.json` fields read-only from existing records.

Only exact SQLite schemas `0d4a342f4c26` (53 tables) and `9b1d0c5e7a42` (54 tables) are recognized. The former is normalized on a new copy using patch004 only; the original is unchanged. Full physical column/FK/index/type/default/generated metadata is recorded in `schema_manifest.json`; a revision label alone is insufficient. Extra SQLite views/triggers are unsupported. PostgreSQL views, materialized views, foreign tables, public routines, noninternal triggers, enabled/forced row security and row-security policies also fail closed. The three reviewed share_widgets CHECK constraints accept exactly the original PostgreSQL16.11 expression and its equivalent pg_dump/restore per-element-cast rendering, with exact table/constraint names and labels; other expression changes remain drift. The optional manifest path accepts only a semantically identical copy of the packaged reviewed manifest; it cannot authorize a schema extension. Duplicate JSON keys and ambiguous values are rejected.

Transfer uses plain physical values, never ORM bind/result converters. Password hashes, ciphertext, UUID bytes and compressed bytes are preserved. JSON is decoded exactly once for logical comparison: scalar strings, objects, JSON null and SQL NULL remain distinct; extension keys and exact number semantics survive. Unsupported JSONB numbers/strings, invalid booleans, text widths and incompatible timestamps fail before a commit. The nullable vendor-app self-cycle is restored explicitly in two phases. Source seed values/IDs replace fresh target seeds; generated PG search vectors are regenerated. The single reviewed `tier_id_seq` has its static definition fingerprinted separately from its counter. Import reconciles its next usable ID transactionally: positive maxima advance the sequence, empty/zero/negative-only tables retain its minimum, and the maximum integer remains exhausted. A failed or interrupted transaction restores the prior sequence state.

The entire relational state, readiness and restricted checkpoint commit atomically. Inserts use 250-row batches within that transaction; rows and sorted canonical digests are materialized per table, so memory must accommodate the largest table. This tool does not claim streaming or bounded-memory transfer. Retry binds original/normalized source hashes, manifest, target identity, all table evidence, semantic mapping and exact original keys. A completed matching retry can recreate a missing mapping file after a post-commit crash. Different keys, mapping, source, target or data are refused. A different output pathname alone is not a new identity.

## Restore boundaries and companions

Before new PostgreSQL writes, the intact compatible SQLite copy can serve as rollback only with its original keys, storage, Redis and explicit nonmutating mode. After any PG writes, that old SQLite copy is stale. Quiesce writers and export a NEW database:

```sh
python -m scripts.workspace_migration export-sqlite --root /offline --output /offline/restored.db --quiesced --mapping /offline/input-map.json --mapping-output /offline/restored-map.json
```

Export constructs a new SQLite9b1 schema through actual migrations, applies the inverse complete raw mapping, verifies every table/hash/FK and publishes only after success. PG-generated search columns and restricted administrative metadata are intentionally excluded. Start a writable deployment COPY of the immutable output with original companions and `DATABASE_TYPE=sqlite`, `DB_PATH=/data/openbb.db`, `WORKSPACE_DB_ACTION=serve`. Reimport into a new provisioned/migrated PG database to regenerate search vectors/indexes.

A PostgreSQL-native full database dump/clean restore is a separate required recovery path. Preserve role definitions/grants, server configuration, protected mapping, the four original keys, `/data/storage`, and `/data/redis` alongside the database backup; a database dump does not contain those companions. Restore into a clean dedicated database with the approved roles and verify the same image's actual login/session/PAT/crypto/settings/app/share/docks behavior before considering it usable. The historical import checkpoint remains unchanged in a native restore. It cannot authorize an import retry against the new target; post-write recovery is qualified by complete raw comparison and actual application behavior, independently of the original import checkpoint. For a private dedicated fixture, the tested database operations are `pg_dump -Fc` followed by `pg_restore --clean --if-exists --exit-on-error` into a newly provisioned database. Do not claim recovery from dump metadata alone.

## Runtime budgets and behavior

The actual active factories are async read/write and one synchronous task engine. Each defaults to pool size2, overflow0, acquisition30s, connection10s, statement30s and lock5s; WORKERS must be1. Two processes permit12 runtime connections, plus the accepted key-mode settings4. Maintenance is explicit and serialized. Stop Workspace replicas for fresh bootstrap: its lock-holder plus bounded child pools can require up to seven maintenance connections. Ordinary migration/import/export use one connection. Leave server/admin/TemporalDB capacity outside this allocation. No cluster max_connections setting is changed. TLS uses verifying SSLContext for asyncpg and libpq verify-full for psycopg2, with complete client-cert pairs if selected. URL construction and driver changes preserve literal credential characters; SQL/parameter/DSN values are not emitted by migration/lifecycle failures or the PG slow-query hook.

Selected serve omits the six upstream historical data-repair tasks and dated migration deletion, and validates existing trial/developer relationships instead of initializing them. Ordinary quota resets, usage/cache synchronization and file/save retention remain scheduled as upstream. Lite's existing supervisor has no RQ worker; this profile does not add one. Account/session changes caused by authorized login/logout and normal API writes retain pinned semantics. MCP PATs at this pin support revocation, not an expiry column; auth errors use the existing JSON-RPC transport behavior.

`verify-postgres.sh` is the mandatory disposable-fixture gate; missing required dependencies or any failed/skipped required stage must return nonzero. Its report must identify the exact image and source/manifest identity and include full transfer, two actual instances, PG-native restore, post-write SQLite restore and fresh PG reimport. No live cutover is authorized by fixture qualification.
