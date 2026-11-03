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
