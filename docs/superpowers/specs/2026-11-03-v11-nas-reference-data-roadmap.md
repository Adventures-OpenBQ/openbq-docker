# v11 foundation, NAS deployment and retained reference data

Status: proposed consolidation of the approved v11 work and November 3 NAS authorization. This document does not claim completion or a production cutover.

## Product outcome

BDOBB should supply correctly selected, retained inputs to open-source analysis tools without users assembling data files or integration scripts. v11 establishes data identity, temporal selection, controlled acquisition, retained results and shared query services. v11.5 adds active portfolio-management workflows on that foundation.

The two documentation tracks remain separate and linked: (1) the ODP/source datasets and their Bronze/Silver/Gold representations, and (2) temporal context, acquisition decisions, publications, executions and receipts.

## Current evidence

- Isolated client/host/backend worktrees exist under `<isolated-worktrees>/v11-platform-20261103/`, on `codex/v11-platform-20261103`.
- Retained-result paging, complete-result table integration, saved acquisition policies, schema documentation, signed-price support and timestamp repairs have been implemented. Installed artifacts still lag later source changes.
- Durable acquisition runs are partially implemented and uncommitted. A focused 159-test authority/contracts/package run and 85 client temporal tests passed before the new atomic-finalization test was added. That finalization test is currently RED because `RunService.finalize` does not exist. Do not call task 5 complete.
- Calendar library/route behavior was qualified; retained TemporalDB calendar admission and common consumer resolution remain unfinished.
- The independently reviewed real S&P 500 bootstrap has 503 securities, 500 issuer groups, SEC ticker-confirmed CIK associations and 1,006 retained source captures. It is a local current-observed snapshot, not an admitted temporal dataset or deployed service.
- The NAS is amd64. It already runs the OpenBQ v10 stack, TemporalDB 0.5.0 (source `efd560cb6bbbf6b4eeccdc9d84999e90c94598b3`, migration 32), and an older donor OpenBB Security Master service. The observed TemporalDB database was 10 MB, with zero executions and one succeeded job. These are inventory observations, not backup or upgrade evidence.
- SIP data remains in the older MinIO service at `s3://openbb-delta/ticks_sip/`, physically under `/share/ZFS29_DATA/minio/openbb-delta/ticks_sip`. There are 796 symbol directories plus two progress directories. AAPL has 4,729 dated partitions from 2008-01-07 through 2026-10-06. Directory presence does not prove current Delta membership, readability, row completeness or full symbol/date coverage. Total archive size has not been established.
- Newer OpenBQ and TemporalDB stores use RustFS. SIP has not been migrated there. No NAS services, images or database schemas have been changed in this session.
- Individual EODHD stock and ETF fundamentals worked. Bulk-v2 NASDAQ, NYSE and BATS each returned 403; bulk access is not a prerequisite for v11.

## Deployment approach

Stage the new v11 services beside the existing services using independently named stores, network and credentials, resource limits and loopback-only access. Build and qualify an amd64 artifact; local arm64 qualification cannot qualify it. Enable one catalog/workspace first, then add others through the same repeatable deployment manifest. Do not equate multiple logical catalogs with separate authorization boundaries.

After staged acceptance and a verified backup/restore rehearsal, cut over only the explicitly selected OpenBQ integration. Keep the donor OpenBB stack and original stores until rollback no longer needs them. Application deployment is in scope; NAS firmware/OS updates, stopping unrelated workloads and public exposure are not implied.

## Domain and temporal ownership

Security Master owns security/issuer/listing identities and dated reference facts. TemporalDB accepts retained observations and binds exact versions to executions. Do not deploy the CSV bootstrap as a competing authoritative identifier database.

Use explicit effective-time and knowledge-time mapping. Source effective/known axes, provider publication evidence and local received/accepted timestamps are distinct. A current snapshot cannot establish past local knowledge. Preserve separately sourced classifications and issuer conflicts; leave unresolved venue mappings explicit.

Acquisition is allowed only under saved, scoped, current policies and server-managed provider-account bindings. Query submission freezes relative parameters; immutable execution starts only after eligible accepted inputs are available. Its deadline remains separate from acquisition time. Cache hits perform no provider requests. Unknown coverage is not successful coverage, and an empty response is not automatically proof of a market closure.

## SIP approach

First use authenticated S3 and Delta APIs to inventory the retained archive read-only. Retain table versions, schema, active file inventory, symbol/date coverage, row counts and validation evidence for a bounded sample. MinIO's on-disk object layout is not a directly readable collection of ordinary Parquet files.

Keep MinIO as the legacy source while qualifying a bounded bridge into TemporalDB. Do not copy its internal object directories into RustFS. If migration is justified by measured capacity/operations, make a separate S3-level copy with Delta-history retention requirements, inventory/hash verification and an explicit final synchronization boundary. Never vacuum or delete the source as part of first admission.

## Release boundary

v11 requires an installed, authenticated workflow that selects identities/calendars/prices, acquires missing inputs under policy, retains accepted evidence, opens a safe result widget and replays without provider calls. Include an actual NAS restart and restore rehearsal and one real retained-data example.

v11.5 begins with portfolios and valuation-ready inputs, then the French 25/factor demonstration, skfolio walk-forward evaluation, PCA/HRP, qualified performance, scenarios, costs and recurring portfolio reviews. Rita/MCP grows with each supported service. OAuth/FastMCP can be prototyped behind the existing boundary; adopting a framework does not itself provide scope authorization or satisfy the release gate.
