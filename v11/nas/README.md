# NAS v11 staging

Status: inventory and backup preparation only. No service or schema upgrade has
been performed by these tools. Follow the cross-project roadmap before cutover.

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
