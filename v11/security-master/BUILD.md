# Standalone Security Master image

Status: frozen amd64 qualification image passed 238 offline tests on the NAS
(4 upstream warnings, 322.58 seconds). Real-store admission and service restart
qualification remain pending.

Use only the verified clean source archive described in
`../SECURITY-MASTER-SOURCE-QUALIFICATION-2026-11-03.md`. Verify archive SHA-256
`3ebd2e93d198aa8a1ac26d16730c73dd6db0c747648bd96f44d861dacf268f73` before extracting
it into a new build context. The context root contains `security-master-api/`
and `openbb-deltalake/`, from source
`b4b7f4b68ae200f82b2067dd6ade70a9d425509a`; do not substitute a live checkout.

Build this Dockerfile with `--platform linux/amd64 --target runtime` and explicit
`SOURCE_REVISION`, `SOURCE_ARCHIVE_SHA256` and `RECIPE_REVISION` build arguments.
Use an unpublished local candidate tag and retain the resolved image ID, labels,
architecture, installed versions, recipe hash and source uv-lock hash. The pinned
base and frozen source lock preserve the standalone service dependency set.
No dependencies are installed into the existing provider host or TemporalDB.

Build `--target qualification` separately and run its full service test suite in
a disposable container with networking disabled. A source-only pass does not
qualify this artifact. Qualify authentication, empty/real-store behavior and restart
against a new service-owned store before NAS admission.

Runtime requires private explicit settings, authentication enabled, a strong
preflight secret and acquisition disabled. Use a writable service-owned /data
volume, bounded /tmp and /run/security-master tmpfs, resource caps, a private
network and loopback-only publication. Never invoke `python -m
security_master_api.store` on the real store: that command seeds synthetic fixtures.
Initializing empty schemas or importing real source observations requires a
separate reviewed admission step. Liveness health is not data readiness.

No image publishing, public exposure, donor-stack replacement or shared-store
mutation is part of this recipe.


## Fresh empty-store staging contract

`provision.py` accepts an inspected immutable linux/amd64 runtime image and full
source commit. It creates a new private directory and refuses overwrite. Its
Compose project is `openbq-v11-security-master`, with an internal network, one
owned `data` volume and loopback API port 18089. It never mounts donor storage,
SIP, PostgreSQL or TemporalDB volumes. The runtime retains UID65532, a read-only
root, no capabilities, no-new-privileges, bounded tmpfs, 2GiB memory and one CPU.

The private environment sets `SECURITY_MASTER_ROOT=/data/security_master`,
`SECURITY_MASTER_ACQUISITION=disabled`, `SECURITY_MASTER_SQL=review`, Basic
authentication enabled and fresh independent password/preflight secrets. No ODP
or provider credentials are forwarded. Basic authentication protects this private
staging service; it does not establish workspace/entitlement isolation.

Before startup, a one-off using the same frozen image verifies no relation has
an existing Delta version, then calls `store.tables.ensure` for the 22 declared
`store.schemas.RELATIONS`. All row counts must be zero. Never call the store's
module CLI, seed helper or golden fixtures. Refuse initialization on a populated
or previously initialized store; do not treat it as an upgrade/migration command.
Retain its result privately, then start only the staged service.

Native NAS checks on November3: health200; catalog401 without credentials and200
with credentials; acquisition policy disabled; all22 physical Delta relations at
version0 with zero rows. Repeating those checks across a service restart preserved
the exact version map. Runtime image/source are the qualified ones above. The
NAS's native Docker CLI over SSH supplied complete JSON receipts; the local
Docker-context proxy returned incomplete output for long exec probes and was
not used as acceptance evidence.

This establishes an authenticated empty service and persisted empty schemas.
Real S&P500 admission, ambiguity/provenance queries, HTTP reference bridge,
workspace authorization and cross-store restore remain unqualified. Keep the
existing services selected until the roadmap's release gate passes. Rollback
stops this staging project and retains its volume; it does not delete the store.
