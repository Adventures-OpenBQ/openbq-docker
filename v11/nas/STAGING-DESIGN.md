# Initial NAS staging bundle

This implements the preparation boundary of roadmap task 2. It does not start
containers or authorize a traffic switch. The accepted deployment must still
qualify image labels, initialize catalogs, register the runtime archive and pass
readiness/restart/recovery checks.

`prepare_bundle(output, release_receipt, port=18088)` creates a new mode-0700
local directory with mode-0600 configuration files. It accepts only an immutable
image digest, a full source commit and linux/amd64. It never edits an existing
bundle and never discovers/forwards production credentials.

The Compose project is `openbq-v11-staging`: postgres, RustFS, API and worker;
project-owned named data/archive/evidence volumes; no external network or
production mounts. Only the API is published, on loopback. Fixed source-pinned
PostgreSQL/RustFS images match the existing qualification fixture. The API and
worker use the supplied immutable candidate image, with pull disabled. Their
control DSNs are separate. A third catalog-only login owns the fresh hot schema;
it must have no control-role membership. Runtime credentials are separate from
administrative migration credentials.

Initial configured memory caps total 4 GiB: postgres 512 MiB, S3 512 MiB, API
1 GiB and worker 2 GiB. These are proposed containment limits, not capacity or
performance qualification. Measure available/reclaimable NAS memory and staged
resident memory before startup/admission; stop only the staged project if it
cannot operate within its limits. Do not reconfigure unrelated workloads.

No provider credentials, acquisition-run permission or fabricated identity map
is provisioned by default. Identity map is empty, provider configuration empty,
and environment digest deliberately UNPROVISIONED. The runtime fails closed until
provisioning has migrated the new DB, created least-privilege roles, initialized
owned bucket/catalogs, registered the actual image/runtime archive and replaced
the digest in private runtime configuration. Never substitute a placeholder or
weaken readiness to start an incomplete service.

Later server provisioning must inspect the actual image architecture/source,
transfer this private bundle without printing it, initialize only its named
stores and retain a credential-free receipt. Rollback stops the staged services
and leaves the previous deployment selected; it does not remove data volumes.
