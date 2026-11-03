# Legacy SIP read-only qualification checkpoint

The source remains the older MinIO service at `s3://openbb-delta/ticks_sip/`,
backed by `/share/ZFS29_DATA/minio/openbb-delta/ticks_sip`. It has not been
migrated into the newer RustFS stores. No source files, Delta logs, tables or
vacuum policies were changed.

The filesystem inventory found 796 symbol directories and two progress
directories. The subsequent authenticated Delta metadata read opened AAPL at
version 1000: 4,729 active files/partitions from 2008-01-07 through 2026-10-06.
This confirms active Delta membership for AAPL, not only path existence.

Three active-partition readability samples were read through Delta/Arrow:

| Symbol | Day | Delta version | Rows from file metadata | Rows sampled |
| --- | --- | --- | --- | --- |
| AAPL | 2008-01-07 | 1000 | 399,068 | 2,048 |
| AAPL | 2026-10-06 | 1000 | 592,896 | 2,048 |
| MSFT | 2008-01-07 | 1003 | 178,205 | 2,048 |

The samples had no null timestamps or prices. This is not full validation of
those partitions or the entire archive: duplicates, ordering, source completeness,
all-symbol coverage, checksums of every object and total archive bytes remain
unqualified. File membership was taken from selected Delta versions, not a
filesystem Parquet glob. Private receipts retain observation times and hashes
of the active-file manifests; no provider data is committed here.

Schema fields include `date`, `price`, `size`, `seq`, `mkt`, `sub_mkt`, `sl` and
partition `day`. The Delta date type is `timestamp_ntz`, read by Arrow as
`timestamp[us]`: it carries no timezone. The legacy loader source documents
millisecond provider timestamps, but file contents alone do not establish the
complete original time/provenance interpretation. Review that mapping before
normalizing into v11's explicit-UTC timestamp contract; do not silently assume a
viewer zone. Price validation must continue to permit signed values where valid.

Next: retain a paginated S3/Delta inventory and source-time policy, qualify a
bounded importer with duplicate/order/precision cases, then admit one sample
through TemporalDB's normal capture/publication path. Any S3-level copy into
RustFS needs its own history-retention, verification and cutover plan. Keep MinIO
as the source until that plan is qualified; never copy its internal storage
layout directly into RustFS.
