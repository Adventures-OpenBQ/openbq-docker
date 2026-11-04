# v11 Completion and NAS Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, following the user's native-execution preference. Steps use checkbox (`- [ ]`) syntax for tracking. Obtain one independent final review of the release candidate before deployment cutover.

**Goal:** Finish the v11 data foundation and run a qualified NAS installation that retains Security Master, calendar, price and bounded SIP inputs for reproducible queries.

**Architecture:** Complete the approved acquisition/run workflow, integrate Security Master through an explicit reference bridge, and retain source evidence in TemporalDB. Deploy an amd64 candidate beside current NAS services; qualify it before selecting a traffic cutover. Keep legacy SIP MinIO data intact and treat its eventual RustFS migration as a separately gated operation.

**Tech Stack:** Existing Python/PostgreSQL/DuckDB/object-store services, Delta-backed Security Master, OpenBB/ODP adapters, BDOBB managed widgets and authenticated MCP/Rita; Docker Compose on the amd64 NAS.

**Spec:** `docs/superpowers/specs/2026-11-03-v11-nas-reference-data-roadmap.md`.

## Global constraints

- Use the existing isolated worktrees and preserve unrelated changes; do not merge or push main implicitly.
- Do not deploy partial task 5 or advertise provider-backed runs before task 7 is qualified.
- Build an amd64 artifact for the NAS; arm64 source/image receipts are not deployment proof.
- Stage independently named stores, network and credentials, resource limits and loopback-only access.
- Keep source effective/known axes, publication evidence and local received/accepted times separate.
- Security Master owns domain identities; TemporalDB retains accepted inputs and execution evidence.
- Preserve signed prices; completeness and identity checks must not impose a universal nonnegative-price rule.
- Keep the existing SIP MinIO archive unchanged; no vacuum, source deletion or filesystem-level object-store migration.
- Individual EODHD endpoints are the working acquisition path. Bulk-v2 access remains unavailable and optional.
- Reuse authenticated MCP and the safe widget protocol. Framework adoption does not substitute for authorization.

## Work roots and existing plans

`H` = `<isolated-worktrees>/v11-platform-20261103/host` (this plan).
`P` = sibling `temporaldb`; `C` = sibling `bdobb`.

Continue C's approved `docs/superpowers/plans/2026-11-03-temporal-widget-gap-closure.md`, tasks 5–9, rather than reimplementing tasks 1–4. Preserve its existing ledger and rulings. The approved dated-calendar design lives in P at `docs/superpowers/specs/2026-11-03-market-calendar-temporal-integration-design.md`.

This is the cross-project execution order. Keep the detailed acquisition plan as its subsystem plan. Before implementing the reference bridge, NAS deployment or SIP importer, write a short subsystem plan that freezes the exact source/adapter contract discovered in its first step; do not silently invent source field or receipt semantics.

## Review focus

- Worker failure between accepted publication and execution creation must not start duplicate executions or lose an authorized waiter (task 1).
- A newer issuer mapping, classification or calendar correction must not rewrite an earlier retained answer (tasks 3–4).
- NAS memory pressure and restart must not silently convert retained evidence into transient local cache state (tasks 2, 7).
- A SIP Parquet object visible on disk may be obsolete or outside the selected Delta version; only the selected table's active files count (task 5).
- Read-only credentials, copied widgets and changed scopes must not trigger acquisition or reuse a prior scope's result (tasks 1, 6).

## Milestones and dependencies

| Milestone | Depends on | Independently reviewable result |
| --- | --- | --- |
| A — Finish query-run plumbing | Existing tasks 1–4 | Durable policy-controlled acquisition and accepted-input execution |
| B — Prepare NAS staging | Current inventory | Backup/restore evidence, repeatable isolated deployment and capacity budget |
| C — Install Security Master | B; existing source qualification | Authenticated reference service and retained S&P 500 source admission |
| D — Retain calendars and prices | A, C | One temporal input path with explicit coverage and assumptions |
| E — Qualify legacy SIP | B; then C/D for admission | Read-only inventory and a bounded validated TemporalDB import |
| F — Connect Rita/widgets | A, C, D | Shared run controls and traceable displayed results |
| G — Qualify and release v11 | A–F; bounded SIP evidence only | Reviewed amd64 NAS deployment, restart/replay/restore and tutorial |

B and the read-only part of E can proceed while A is completed. Production replacement waits for G. Full SIP migration does not block v11; a truthful inventory and bounded integration example are enough.

### Task 1: Complete the approved acquisition subsystem

**Files:** P `migrations/034_acquisition_runs.sql`, `temporaldb/acquisition/runs.py`, `temporaldb/api/acquisition.py`, `tests/test_acquisition_runs.py`; subsequent preflight/orchestration files and migrations from existing tasks 6–7; P/C contract schemas and generated types.

**Interfaces:** `RunService.submit(scope, request, accounts=...)`, `status(scope, run_id)`, `cancel(scope, run_id)`; fenced `finalize(lease, manifest, environment_digest=...)` returning a ready handle only after atomic execution creation. Continue the approved `preflight(...)` and `advance_run(...)` contracts.

- [ ] Finish the currently RED accepted-input finalization test: forged manifest refuses; accepted manifest starts exactly one execution; retry cannot duplicate it; interactive execution gets its own 60-second budget. Add a revocation/finalization race test before implementation.
- [ ] Implement the narrow worker finalizer and preserve current lease fencing, immutable execution and API/worker role separation. Watch the new tests pass.
- [ ] Complete approved tasks 6–7: bounded coverage, negative evidence, provider/account-safe operation sharing, durable capture, normalization, publication and retry/cancellation. Qualify EODHD and yfinance separately.
- [ ] Verify no network on cache hit/replay; no historical-knowledge backfill from today's acquisition; no execution while waiting; one cancelled waiter leaves the other active. Test crash/restart across publication/finalization.
- [ ] Run focused authority/provider tests, the applicable full backend gate and client contracts/type checks. Record every failed/skipped check and regenerate schema documentation. Commit coherent changes in each owning repository.

**Gate:** A real bounded daily-price miss can become accepted retained inputs and an execution under policy; a cache hit performs zero provider requests.

### Task 2: Make the NAS deployment repeatable and recoverable

**Files:** Create H `v11/nas/inventory.py`, `v11/nas/compose.staging.yaml`, `v11/nas/provision.py`, `v11/nas/README.md`, `tests/test_nas_staging.py`; retain credential-free receipts under `v11/qualification-2026-11-03/nas/` and private backup artifacts outside Git.

**Interfaces:** `inventory(target) -> sanitized receipt`; `provision(target, release_manifest) -> deployment_receipt`. Deployment receipt identifies image/source digests, architecture, service/store names, configuration fingerprints, health checks and rollback target; contains no credentials.

- [ ] Retain the observed services, selected Compose definitions/image IDs, mount ownership, PostgreSQL migration level, bucket/catalog inventory and memory/disk budget. Inspect configuration without printing secrets.
- [ ] Back up the selected existing TemporalDB configuration/database and inventory referenced archive/object data. Rehearse restoration into a new target and compare protected references; do not label a database-only dump a complete cross-store backup.
- [ ] Test generated staging configuration cannot attach production volume paths/networks, publish non-loopback ports or reuse production credentials by default. Test failed health admission leaves the current deployment selected.
- [ ] Build/package the reviewed P commit for linux/amd64; verify packaged migrations, locked extensions, archive hashes and source labels. Provision dedicated PostgreSQL/RustFS storage and separate API/worker logins; do not grant policy-write permissions by default.
- [ ] Start only the staged project under a measured resource budget. Verify health/readiness, authenticated discovery, role separation and persistent restart. Retain the deployment receipt and commit code/docs only.

**Gate:** Re-running provisioning is safe and bounded; staging operates on its own stores and can be removed without changing current services or SIP.

### Task 3: Qualify and install Security Master

**Files:** H new `v11/security-master/` source lock, build/Compose configuration and qualification harness; recover reviewed tracked `security-master-api/` source into the isolated H tree. Modify the isolated `openbb-security-master` adapter only after ownership/dependency reconciliation; test identity/context/receipt boundaries.

**Interfaces:** Authenticated `ReferenceResolve`, `ReferenceSecurity` and the selected `MarketCalendar` source response, with explicit temporal context and dependency receipts. Freeze the response/receipt mapping in the subsystem plan before writing the bridge.

- [ ] Record exact donor commits and compare the already running donor NAS service with the recovered source. Confirm the standalone service and adapter have separate dependency needs.
- [ ] Resolve the adapter's OpenBB-core `<2` declaration against v11 core 2.0.1 in isolation. Keep the existing calendar namespace owner; initially add reference routes only.
- [ ] Run identity ambiguity, share-class, context, receipt and unauthorized-access tests against a dedicated fixture store. Confirm field-level classification support rather than advertising assumed coverage.
- [ ] Start the qualified service against its own staged store. Keep acquisition disabled until task 1 can authorize it. Do not treat shared Basic authentication as workspace isolation.
- [ ] Import the reviewed S&P 500 bootstrap through a provenance-preserving source admission step. Retain raw sources and selected CIK evidence; preserve unresolved CBOE MIC and distinguish current-observed membership from historical membership.

**Gate:** An authenticated query resolves a real security with inspected provenance; ambiguity refuses; the S&P 500 source package has not become an undocumented parallel master.

### Task 4: Retain dated reference inputs and prices

**Files:** P new `temporaldb/reference/` adapters/retention code and next available migrations; `tests/test_reference_retention.py`, `tests/test_calendar_resolution.py`; C/H calendar consumers named in the approved calendar design; P `docs/schema/` dictionaries and generated references.

**Interfaces:** A versioned retained-reference contract binding source receipt/dependency versions, local capture identity, temporal context, coverage and normalization/resolver version to execution inputs. Source Delta versions remain distinct from TemporalDB catalog pins.

- [ ] Freeze the strict reference contract and dataset admission mappings from actual source responses. Test corrected mappings preserve previously selected retained answers.
- [ ] Retain exact bounded Security Master/calendar responses and normalize accepted reference publications. Keep received/accepted/publication/effective evidence separate; reject unsupported past-knowledge claims.
- [ ] Implement the shared dated-session resolution path. Test closed versus uncovered, early closes, breaks, DST, daily-date preservation and correction replay across client/server consumers.
- [ ] Connect retained prices through task 1's policy path with dated listing identity. Show missing price coverage separately from missing calendar coverage; include signed-price fixtures.
- [ ] Add requested/resolved assumptions and exact reference IDs to the versioned execution linkage and documentation. Run contract, isolation and replay tests, then commit.

**Gate:** Two runs can deliberately select different knowledge/effective contexts and explain their differences using retained evidence.

### Task 5: Inventory and qualify the legacy SIP archive

**Files:** Create H `v11/sip/inventory.py`, `v11/sip/README.md`, `tests/test_sip_inventory.py`; add a separate P managed-import adapter/plan only after inspection. Retain bounded source receipts outside Git where licensed data is involved.

**Interfaces:** Read-only S3/Delta inventory returning table URI/version, schema, active-object manifest, symbol/day coverage, row counts/quality, validation failures and observation time. The later importer consumes an exact selected manifest, not a mutable filesystem glob.

- [ ] Use authenticated S3/Delta reads on MinIO; establish active table versions and schemas. Measure total size with bounded/paginated object inventory; avoid an unbounded recursive NAS filesystem scan.
- [ ] Validate AAPL on two dates plus one other symbol/date selected from the inventory. Check row readability, ordering, timestamp units/precision, duplicates and source/session fields. Do not infer market-wide completeness from three samples.
- [ ] Test obsolete Delta files and incomplete listings cannot become admitted coverage. Test the importer preserves its selected version despite later source changes.
- [ ] Admit one bounded sample into separate TemporalDB Bronze/Silver/Gold paths with real source provenance and replay evidence. Keep legacy and locally captured SIP knowledge semantics explicit.
- [ ] Decide whether to retain MinIO as a bridge or schedule an S3-level RustFS migration using measured bytes/history requirements. Migration requires a separate copy/verification/cutover plan; no deletion or vacuum is part of this task.

**Gate:** We can state what is retained, what was validated and what remains unknown without altering the source archive.

### Task 6: Complete widgets and Rita/MCP integration

**Files:** Existing gap-plan task 8 client run controls/bindings, backend MCP tools and gateway route classification; tests for permission/scope lifecycle, atomic pin/copy and managed result receipts.

**Interfaces:** Shared submit/status/cancel and read-only discovery/preflight/result services; widgets retain execution identity and complete-versus-loaded-page semantics. Acquisition-capable MCP tools are explicitly classified as writes.

- [ ] Implement atomic pin/copy before enabling acquisition-capable bindings. Test read-only credentials, duplicate widget requests, stale scopes and shared-operation cancellation.
- [ ] Show requested/resolved settings, policy revision, coverage/gaps, source/reference identities and execution receipts in widgets. Controls persist explicit choices for future runs.
- [ ] Qualify the actual Rita connection against the same service. Test more than 1,000 rows, filtering outside page one, complete-result sorting/pivot/export and retained replay.
- [ ] Prototype OAuth/FastMCP separately only if needed for the selected client connection; preserve current authentication while testing audience, issuer, scope and revocation. Do not block v11 on a framework rewrite.

**Gate:** Rita and a direct widget request yield the same retained execution/result identity under equivalent inputs and authorization.

### Task 7: Release qualification, tutorial and NAS cutover

**Files:** H `v11/nas/README.md`, `v11/RUNBOOK.md`, release locks/acceptance receipts; P `docs/schema/` tutorial and release acceptance; C installed/browser acceptance and source offer/runtime pins.

- [ ] Freeze all participating commits/artifacts and run the installed amd64 flow with real retained reference/price data and the bounded SIP example. Reconcile generated contracts, gateway routes and the packaged native client.
- [ ] Exercise restart, policy revocation, scope isolation, concurrent waiters, exact export, corrected-current versus retained-prior answers and replay without network. Rehearse restore on NAS-backed storage and record measured resource use.
- [ ] Publish a basic tutorial within the repository: source/ODP payload → Bronze → Silver → Gold → temporal selection → immutable execution/receipt → widget. Include one correction and explain negative prices and current-observed identity limitations.
- [ ] Obtain independent review, fix material findings and rerun affected gates. Prepare exact deployment and rollback commands around immutable image/config/source identities.
- [ ] Switch only the selected OpenBQ integration after staged acceptance; verify the real client and Rita. Retain the former deployment and MinIO source as rollback evidence. Record what changed and what did not qualify.

**Gate:** v11 is release-ready only with passing installed evidence and a demonstrated rollback/restore path, not merely a green source test suite.

## Publication order after the foundation

Treat these as weekly demonstration targets, not promises to ship unfinished infrastructure. Build two completed episodes ahead where practical.

| Target episode | Demonstrable product increment | MCP/Rita increment |
| --- | --- | --- |
| Foundation special | NAS services, Security Master, retained data and correction/replay tutorial | Authenticated discovery and traceable queries |
| 1 — The portfolio remembers | Real portfolio import/reconciliation and month-end holdings | Portfolio/temporal position discovery |
| 2 — Data ready for analysis | Dated prices, classifications, benchmark/returns and French 25 package | Input preparation, coverage and assumptions |
| 3 — Bring your own factors | Source-correct FF3, FF5 and FF5 plus momentum | Factor discovery, selection and exposure questions |
| 4 — Walk forward | skfolio model selection with frozen folds, leakage controls and objective-specific evaluation | Submit/evaluate/retrieve analysis runs |
| 5 — See diversification | PCA, clusters, HRP and risk contributions | Linked analysis widgets sharing input identity |
| 6 — Evaluate the explanation | Stability, residuals, uncertainty and qualified model appropriateness | Evidence-backed answers; causal research is guidance, not proof |
| 7 — Explain performance | Qualified account/benchmark performance; OpenPort where verified | Period-performance dashboard and report |
| 8 — Test a change | Hypothetical allocation/exposure/risk comparison | Scenario creation/comparison separate from portfolio records |
| 9 — Rebalance realistically | Turnover, costs and constraints; add another library only for a demonstrated gap | Policy simulation with saved assumptions |
| 10 — Watch and review | Authorized schedules, meaningful alerts and recurring portfolio review | Scheduled execution, inspection and decision notes |

Maintain an Arcana-style question acceptance ledger: supported question, required inputs, service/tool, widget, assumptions, evidence and explicit gaps. Match demonstrated workflows rather than model-provider counts.


## November 4 execution reconciliation

The checkboxes above retain the original build sequence. Current evidence and
scope dispositions are in the [final candidate report](../../../v11/FINAL-QUALIFICATION-2026-11-04.md)
and [verbatim decision ledger](../../../v11/EXECUTION-DECISIONS-2026-11-04.md).
Tasks 1–4 have source and native staged qualification: bounded acquisition,
repeatable independent stores, admitted real Security Master, retained references,
dated calendars and one real EODHD price range. Recorded Yahoo and installed
SDK tests are distinct from live Yahoo sourcing, which remains unqualified.
Task 5 is formally narrowed to bounded retained SIP inspection, as permitted by
Milestone G; whole-archive certification/migration and canonical analytics remain
open operational work. Task 6 includes actual authenticated MCP/Rita and native
widgets with matching frozen receipts; OAuth issuer/public TLS remain separate.
Task 7's candidate artifacts, tutorial, independent review and recovery are
tracked by the final report. Its production switch/merge/publication instruction
is not executed implicitly and remains a separate integration decision.
