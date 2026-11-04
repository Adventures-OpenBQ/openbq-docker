# NAS v11 staging

The qualified candidate is now running as a separate live v11 deployment.
See [live ports, verification and tested rollback](../NAS-LIVE-2026-11-04.md).
The dated staging instructions below retain the original build sequence.

Current November 4 candidate: migration 044, native amd64 API/worker/MCP, real
retained reference/calendar/price data and bounded SIP inspection. The original
production selection is unchanged. See [the final qualification report](../FINAL-QUALIFICATION-2026-11-04.md)
and [artifact receipt](qualification-2026-11-04.json) for the current source,
review and recovery status. The dated observations below describe earlier
staging steps and do not supersede that receipt.

## Inventory

Run `python v11/nas/inventory.py --ssh-target nas --docker-context nas --output NEW_PATH.json`.
The operator's existing SSH alias and Docker context provide transport. Inventory
reads host architecture/memory/filesystem metadata and at most 128 containers.
The Docker template excludes environment variables, commands and logs at the
collection boundary. The output additionally filters labels and network fields.
Use a new output path for every observation. Do not commit private receipts.

Read-only integration test (requires the selected existing NAS service):

```sh
NAS_INVENTORY_TEST_CONTEXT=nas NAS_INVENTORY_TEST_CONTAINER=openbq-temporaldb-temporaldb-api-1 python -m pytest tests/test_nas_inventory.py -q
```

November 3 observation: NAS x86_64, 68 running/stopped containers inventoried.
Existing TemporalDB API/worker have 4 GiB container limits each. The older
Security Master service and current database/object store have no configured
container memory limit. These facts do not establish free capacity or authorize
changing unrelated containers.

## Backup preparation

A private configuration snapshot and online custom PostgreSQL dump were retained
server-side under `openbq-v11-staging/backups/preupgrade-20261103T185732Z`.
The dump's archive directory was read successfully by the installed pg_restore;
SHA256SUMS records the snapshot/dump/listing bytes. No secrets were printed or
committed. This is not a complete cross-store backup or a restore rehearsal:
writers were not stopped, object data and runtime/evidence archives were not
copied, and restored replay has not been checked.

## Next staging boundary

Use a dedicated `openbq-v11-staging` Compose project/network and newly named
PostgreSQL/RustFS volumes, distinct credentials and loopback-only API access.
Require an inspected amd64 image digest and explicit resource limits before
startup. Do not attach the existing MinIO, TemporalDB or donor Security Master
volumes. Do not connect staging to the current gateway until installed acceptance.

The SIP archive remains in the older MinIO `openbb-delta/ticks_sip` namespace.
Its internal object directories must not be copied into a RustFS data directory.
Source Delta/S3 inventory and a bounded import precede any migration decision.

## Prepare a private bundle

`python v11/nas/provision.py --release-receipt VERIFIED_AMD64_RECEIPT.json --output NEW_DIRECTORY`
prepares files locally without starting containers or changing the server.
See `STAGING-DESIGN.md` for the required initialization sequence and containment
limits. Generated credentials are fresh and private; never commit the bundle.
The runtime deliberately refuses to start with its UNPROVISIONED digest.

## Fresh-store bootstrap

`bootstrap.py` runs inside the inspected candidate image with the private bundle
mounted read-only at `/config`. Run it as a one-off on the staging network with
only the staging archive/evidence volumes writable; runtime services retain their
read-only archive mount. The one-off needs CHOWN/DAC_OVERRIDE for assigning its
new archive files to runtime UID 65532. Never mount existing service volumes.

Bootstrap verifies the restricted configuration, migrates the new control DB,
creates separate runtime/catalog logins, initializes the staging bucket and hot
catalog, verifies role boundaries, and archives the actual NAS runtime. Retain
its credential-free JSON result privately. Register its environment digest in
both private runtime files before starting API/worker. Never rerun it against an
active store or replace credentials on existing roles.

The November 3 native amd64 candidate uses TemporalDB source `d2d31ff63d9b`
with migrations through 034. It does not include the later pure acquisition
planner or a provider orchestration worker. Acquisition remains disabled.
A saved AAPL query definition survived restart; no price data was acquired.
This is metadata durability evidence, not cross-store backup/replay evidence.

Guard tests: `python -m pytest tests/test_nas_bootstrap.py tests/test_nas_inventory.py tests/test_nas_staging.py -q`.
The local Docker bootstrap profile requires `NAS_BOOTSTRAP_TEST_IMAGE`; the NAS
inventory profile requires its explicit context/container settings. An unconfigured
profile skips rather than claiming an integration pass. Local broad backend
regression was interrupted by Docker VM disk exhaustion; a fresh isolated
protected-publication reproduction subsequently passed. Do not weaken the tests
or prune unrelated Docker data to bypass that capacity gate.

## Managed Yahoo interpreter artifact

`Dockerfile.managed-yahoo` builds the reviewed provider source archive separately
from TemporalDB's Python environment. The archive is pinned to source
`d867c8bb64fda4dc843146a44f46ec7ca17e0ae8` and SHA-256
`b61b6be5d672497db521978fb58b61a89059dcccfdc003c5d47607f3a8b826a7`.
The SDK target was built natively for linux/amd64 as
`sha256:b837a2a4ac871ac43cd8cfc6b30efa374a1b6ef1489e51ac11098a672e5f3922`.
A nonroot, read-only, network-disabled NAS smoke check imported the provider's
historical model and decoded codec successfully. Installed versions were
openbq-yfinance11.0.0, OpenBB core2.0.1, yfinance1.7.0, pandas3.0.6 and numpy2.5.3.

For the final `runtime` target, supply the qualified immutable TemporalDB base
image explicitly using `TEMPORALDB_BASE_IMAGE`. The SDK is copied under its own
interpreter path; it does not change TemporalDB's installed dependencies. Retain
both source identities, recipe hash, base/final image IDs and the native SDK
profile. Worker configuration must select that exact interpreter/profile and a
server-owned account binding. Building this SDK target does not enable
acquisition or qualify the combined runtime. Combined-image qualification and
staged service selection remain separate release steps.

## Bounded qualification image updates

The three additional Dockerfiles are operator recipes, not default releases.
Pin their base by verified immutable image ID and retain source/tree, wheel and
recipe hashes before using them. `runtime-wheel-update` replaces only the exact
checked universal TemporalDB wheel, with dependency resolution disabled. Check
installed package file hashes and archive the resulting native runtime separately.
It does not prove the clean source image build passed.

`table-runtime-modes` repairs only named public health/license/source manifest
files masked by a private export umask; `browser-runtime-modes` normalizes only
clean public qualification source/assets, skips symlinks and retains a nonroot
runner. Neither recipe grants access to private configuration or licenses market
data for publication. The browser runner is qualification tooling, not deployment.

Keep source ingestion byte limits consistent: retained backend acquisition is
clamped by `catalog.limits.max_upload_bytes` as well as backend `maxBytes`. The
bounded SIP qualification uses32MiB for both source and parse limits,2000rows,
64columns and60seconds, with a compatible worker frame bound. A complete query
result must still retain the source-domain inspection warning.

## Final ingestion bundle update

`Dockerfile.table-ingest-update` replaces only the architecture-independent
`child.mjs` and `source.json` over the explicitly supplied qualified native base.
Before using it, compare all native Rust sources, build scripts, Cargo locks and
external JavaScript dependency locks with the base revision; refuse this shortcut
if those bytes differ. The supplied SHA256SUMS checks both copied files. Record
both source identities, base/final image IDs, recipe and installed-file hashes.
The November 4 receipt distinguishes this verified reuse from a clean dependency
rebuild, which failed NAS inode capacity. The original full build recipe and
source lock remain available; the update does not claim reproducible equivalence
to a successful clean build.
