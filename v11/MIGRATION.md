# v11 migration calibration and recovery boundary

Task 9 qualifies a recorded-fixture recovery seam in the standalone sibling
`temporalDB-docker` service (P). This host repository (H) owns deployment image
pins only; the client (C) receives measured evidence under `docs/releases/v11/`.
No live calibration, NAS import, bulk acquisition, image change or cutover is
performed by this procedure. Task 12 must attach real Q3 executions to these
versioned run references; fixture run IDs do not establish Q3 completion.

## Recorded calibration

From P, run `uv run --frozen python scripts/calibrate_v11.py --output calibration.json`.
The default package fixture explicitly contains daily corrections, two FRED
vintages and a tick sample. It reads five recorded responses and makes zero
provider requests. Coverage means dates present in those response records; it
is not exchange-session completeness or a claim about an installed legacy store.
Bytes measure the serialized recorded fixture, not original HTTP wire bytes.
`payload_versions` counts distinct payloads, not semantic assertion revisions.
Latency measures local fixture reading/parsing, not network or production query
latency. Empty coverage cannot support a forecast and fails calibration.

Each scenario states its date units, full-walk units, request ceiling and retry
factor. The lower bound assumes the declared date coverage per response; the
upper bound uses only observed dates and the explicit retry factor. These are
conditional planning bounds from tiny fixtures, not statistical confidence
intervals or a provider guarantee. Pricing and network latency remain null until
reviewed measurements are supplied. Currency cost can be calculated only from
an explicitly supplied per-1000-request price. No credential or network option
is accepted by the fixture calibration API.

A proposed live review must name provider/endpoint, identities and exact date
ranges, response representation, entitlement, credentials held outside artifacts,
maximum requests including retries, stopping policy, concurrency, rate limits,
observed holes/no-trade evidence, request pricing, expected bytes and time bounds.
Use one reviewed bounded slice before proposing a bulk walk. The example daily
252-date, macro120-date and tick20-date scenarios are not an inventory of the
user's holdings and do not authorize their forecast request ceilings.

## Existing data versus acquisition

Copy without refetch, after verifying an explicit legacy inventory:

- Immutable provider response bodies and their truthful capture/receipt metadata.
- Complete PostgreSQL control and DuckLake catalogs, including inlined rows,
  identity mappings/alias history, accepted generation closures, capture outbox,
  exact input vectors, publications/Gold definitions, tick migration checkpoints,
  permanent protected holds and retirement receipts.
- Every object in each explicitly named dedicated bucket, with its original
  bucket/key and content hash; preserve retained physical versions referenced by
  the catalogs, including old files that current queries no longer select.
- Runnable source, all migration resources belonging to the pinned source commit, dependency lock, exact extension
  binaries and platform/package fingerprints; include reviewed deployment/image
  artifacts explicitly. Archive them independently of mutable image tags.
- Legacy Delta/file rows and external namespace mappings, only if an inventory
  establishes their identity and ownership. Label legacy unversioned rows as
  such; copying cannot manufacture past capture clocks or correction history.

Require new, separately budgeted acquisition for missing bodies, historical
ranges never captured, missing identity evidence, unsupported legacy corrections,
unavailable provider release history and uncovered dates. A repeated fetch is a
new receipt. It cannot repair the provenance of an old row retroactively.
Task 9 does not install a Delta importer or fetch any of these ranges.

## Proposed storage layout

Use dedicated PostgreSQL and S3 services for TemporalDB. Keep Bronze immutable,
use distinct hot/cold catalog data prefixes, and retain control authority beside
the DuckLake metadata. Recovery bundles live outside active data volumes and
contain `manifest.json`, `database.dump`, numbered `objects/` files and actual
`artifacts/runtime/`, `artifacts/extensions/`, lock and deployment artifacts.
The manifest retains original bucket/key placement and exact catalog schemas;
restore uses a new S3 endpoint with the same bucket names and a new PostgreSQL
cluster. Secrets, login role passwords, DSNs and credential files remain external.

Current tooling requires dedicated, unversioned buckets. Enabled or suspended
S3 versioning is rejected: preserving S3 VersionIds needs a reviewed adapter.
Catalog snapshot history is retained by the database/object copy. PostgreSQL
server version, DuckDB version/platform, recorded dependency versions, source and extension
hashes must match for replay; upgrades are a separate qualification. Memory-based
fixture volumes qualify recovery semantics, not crash/power-loss durability or
NAS performance. Full-database inventory and whole-object reads are intentionally
bounded administrative tooling; scale/resource qualification remains open.

## Future switchover gate

Stop the named legacy ingestion loop, its schedules and maintenance first;
confirm no second uncontrolled writer is active. Drain or deliberately checkpoint
in-flight jobs without deleting capture/outbox/history state. Capture and verify
the recovery set while writers and expiry/cleanup remain stopped. Rehearse restore
and fallback on separate services. Keep old identity namespace mappings unchanged.

A live pointer/service switchover is a final, explicitly authorized action after
Task 14 Q5: shared-client/server acceptance, scope/fencing/failure checks, full
service/provider/client checks, browser/native persistence, real Q3 protected
replay after revisions/cleanup, independent restored replay, separately recorded
NAS load results and independent whole-change review. Task 9 fixture PASS does
not satisfy those gates. Keep legacy loops stopped while new workers own
acquisition. For failure, stop new workers/maintenance and use the runbook's
compare-and-swap rollback of the exact old publication receipt. Resume only the
reviewed single owner after confirming the restored head and its dependencies.
