# Standalone Security Master image

Status: the updated admission image passed 307 installed-package tests offline
on the NAS (4 upstream warnings, 312.08 seconds). Real data has been admitted
and selected only in private staging. See the admission evidence below; this is
not production cutover or TemporalDB reference-bridge qualification.

The original empty-store baseline used the verified clean source archive described in
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


## Original empty-store staging contract

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
At that baseline, real S&P500 admission, ambiguity/provenance queries, HTTP
reference bridge, workspace authorization and cross-store restore were unqualified. Keep the
existing services selected until the roadmap's release gate passes. Rollback
stops this staging project and retains its volume; it does not delete the store.


## Current-observed S&P 500 admission artifact

The clean standalone source revision is
`e6888f365d1afdf9bcc9ac9516ebabd0a5e1a22f`. Its source archive SHA-256 is
`de4e2b60c3ea5e3a4689ba0324ecfc9ea801a0f8098697e89797e25d3d6784a4`.
The unchanged Dockerfile SHA-256 is
`1e19d370254062aa117c33645555cb49b53cae60dc8335ffeb52c5586617b891`;
recipe revision is `0b6ecfb399aa27a0c648b97560346a782663dd5f`.
Native NAS builds resolved to these linux/amd64 identities:

| Artifact | Immutable image ID |
| --- | --- |
| Runtime | `sha256:32df9ce0c0b1c69a53c91e4ddeebd48009e0e96d51bd988c585a3c7cdd72cd30` |
| Qualification | `sha256:ff5ef0b318535d2550a55fc0087fff7f5d482c3c35b8816e976cf8ad0e33a7b2` |

Qualification copied only the tests into a disposable directory outside the
source checkout, asserted the module origin was installed site-packages, and
ran pytest with no project configuration. The network was disabled and the
reviewed real input volume mounted read-only. All 307 tests passed. The two
images are retained together as a private Docker-save archive, SHA-256
`30582434d0cebd2edc7805db3098186e529ae91348e7525fd081955192d3f329`.

Offline NAS admission verified the separately pinned checksum manifest
`b57e2b87958c8d89fb3e57440c19ab9dac453fce0ba1863f835586dac020ca0a`,
all retained source bytes, declared schemas, join integrity and relation content
hashes. The completed receipt covers 22 relations: 500 issuers; 503 each of
securities, instruments, listings and universe memberships; 2,514 identifier
aliases; 1,006 source captures; and 8,533 Bronze payload rows. Other relations
remain empty. Admission completed at `2026-11-03T21:54:38.454117Z`, which is the
local visibility floor, independently of the earlier provider observation times.

`provision.py --admission-receipt` accepts only an explicitly completed receipt
bound to the inspected image/source and a new owned admission directory. It
refuses incomplete or inconsistent evidence before creating a private bundle.
The existing empty directory is retained. Selection changes only this private
staging service; it does not enable acquisition or forward provider credentials.

Unknown business-effective starts remain null: this current-observed snapshot
cannot answer historical membership or establish past local knowledge. Explicit
dated identity requests refuse unknown history. GOOG and GOOGL retain separate
security/listing/instrument identities and a shared issuer. CBOE's unresolved
canonical MIC remains null. Source weights are not renormalized; classifications
and verification qualifications remain Bronze evidence because the declared
schemas have no normalized classification relation. Dependency provenance is
explicitly package-wide, with a primary capture per assertion, not field-level.

The completion sidecar is required together with the Delta tables for restart
and restoration. Public catalog metadata and the opaque receipt projection
version bind the package identity, completion floor and projection method.
Ops audit appends do not constitute newer reference data. Reference mutations
invalidate admission verification rather than silently changing the master.

Private runtime HTTP/restart evidence is retained separately from the source
archive and image receipts. TemporalDB's retained reference bridge, calendar and
price integration, workspace authorization, cross-store restore and production
release gates remain separate unfinished work.

Native authenticated HTTP checks passed before and after a container restart:
AAPL ticker and ISIN resolve to the same security; GOOG/GOOGL preserve their
separate instruments and common issuer; CBOE preview retains a null MIC;
anonymous catalog requests return401; known-at before the floor returns404;
explicit2020 identity requests return404 with unknown-history qualification.
Catalog reports no newer reference data after only audit writes. The complete
reference relation versions, content hashes, package identity, visibility floor
and returned domain IDs were identical across restart.

An independent whole-subsystem review found no Critical or Important issue.
Deferred minor: the host bundle generator accepts a nonempty but truncated
relation-proof map. Native startup independently verifies the complete22-relation
inventory and fails closed, so incomplete data is not served; bundle-time
inventory validation can be strengthened separately.
