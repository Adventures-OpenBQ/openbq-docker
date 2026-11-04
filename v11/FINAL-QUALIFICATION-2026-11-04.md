# v11 candidate qualification — November 4, 2026

The isolated NAS release candidate passed its final qualification. Publication, production ingress and
merging into main are separate operations. The existing production services and
original MinIO SIP archive remain unchanged.

## Frozen implementation

| Component | Qualified source / artifact |
| --- | --- |
| BDOBB | `4dc87f7f0c0a92479d64e912e6739b304c511e3e` |
| TemporalDB | `9a1cf6f19c40bbe5a4f02d31523981e7d697c7b1`, migration 044 |
| API, worker, MCP | `sha256:e134b38de756eb005d986630edffdc9ab80a419f80513b3521960640e9321b87` |
| Archived runtime | `f11ad9a8d61656df66397c509b1f5a0a85e442eaae171d8a3ab6b1462d8dee31` |
| Managed table | `sha256:cd3620534c8729b0d25e4e998177eeb89a2172c59f767bc3b9e12e7ce3da009b` |
| Table ingestion source | `3014979e457f4317d13ffaf117f16ed51e4fe396`; native Rust/dependency bytes unchanged from the qualified base |
| Security Master | `e6888f365d1afdf9bcc9ac9516ebabd0a5e1a22f` |

See the [machine-readable artifact receipt](nas/qualification-2026-11-04.json)
for checksums and platform distinctions. The unsigned arm64 application builds;
the real interactive qualification uses the production browser UI and gateway
against the native amd64 services. The application was not launched against
shared local storage. Browser authentication uses a synthetic local signed
session, not a qualified public OAuth issuer.

## What the candidate demonstrates

* A real, current-observed S&P 500 master: 500 issuers and 503 securities,
  retained source evidence, distinct share classes and explicit unresolved
  identity/history boundaries.
* Retained reference responses and dated XNYS, XHKG and XSHG session bundles,
  with observation, effective and knowledge clocks kept separate.
* Saved-policy acquisition, bounded source requests, accepted publication and
  immutable executions. Recorded EODHD and Yahoo paths cover sharing,
  cancellation, correction, restart and authorization cases. The native live
  acquisition demonstration is one EODHD daily-price range, not live Yahoo.
* Cursor paging, complete-result managed sorting/filtering/pivot/export, pinned
  execution reloads, and matching API/MCP/widget receipt identities.
* A bounded SIP inspection with all 2,048 original sampled observations retained,
  1,788 exact corroborated tuples and 260 excluded observations. It is not a
  canonical tick dataset or a complete archive analysis.

## Final review and one fix pass

One fresh-context independent whole-release review found no confirmed Critical
issues and two Important/P2 findings. Both were accepted and fixed. No second
review is claimed and no Minor finding from this final review was deferred.

**Durable acquisition explanations.** Migration 044 exposes a worker-fenced
snapshot of the original run and policy revision, execution assumptions,
cache/provider decision and selected accepted coverage/publication references.
The execution receipt retains that explanation through API/MCP, pin/reload,
managed-table provenance, export and protected replay. Later policy changes do
not rewrite it. Ordinary and legacy receipts are not retroactively labelled
cache hits. Account references and credentials are excluded. Operational budget
ledgers remain separate; provider-operation counts are not a complete count of
SDK-internal HTTP calls. Large explanations remain subject to existing bounded
source/receipt response limits; no silent truncation or budget increase was added.

**Exact inspection presentation.** Both Temporal table adapters explicitly
preserve full naive and UTC timestamp text and exact integer identifiers. They
do not infer a missing timezone. Raw values and exports retain their semantics.

**Stable visible rows.** Native instrumentation reproduced a 44,130-pixel virtual
viewport inside a 468-pixel card, which rendered 1,598 rows and thrashed the
12-block cache. The final layout constrains the table to its card. The clean
acceptance run has a 344-pixel viewport, 34 rendered rows, six commands, zero
cancellations and zero pending requests. Source and service guards were not
raised for this fix. Two expected discovery 404s remain. Earlier failures are
retained: a test exported before filter publication, and a reused-service attempt
received a bounded rows 413. The final isolated cases start the owned transient
table process with the same limits; no canonical data is deleted. The isolated
413 is not presented as a diagnosed source-code defect or proof that every
long-running resource scenario is qualified.

## Real receipt and interface evidence

The native miss execution `82d43ffb-961d-4364-ba93-36bb57780cde` retains
`provider_backed`; the following execution
`98247287-5f09-4639-834b-2f3d1d7ce6e8` retains `cache_hit`. Both reference policy
`fb3d6d8d-12e1-4f6b-bc82-86e367beff75`, revision 2. The miss adds one operation
and one capture; the hit adds neither. This is actual retained data for
`XYZ.US`, January 21, 2025, with the admitted dated identity mapping.

The selected fresh coverage capture differs from the value-deduplicated Gold
row's older capture lineage. Their exact retained raw body SHA256 values match,
and actual OHLC values were independently checked against that body. Coverage
freshness revalidation and row-value lineage answer different questions; a new
capture does not imply changed market values.

Both actual pinned receipt widgets pass original revision/reference checks,
reload and exact JSON explanation export. Rita makes one genuine retained-result
MCP call through the production client agent loop and reports the same decision,
policy ID and revision. The native browser gateway and Rita/MCP qualification
use read-only retained-result credentials; the live acquisition submission uses
a separately authorized operator API key. Interactive submission/cancellation
and acquisition-capable MCP contracts have source/authentication tests, not a
claim that Rita or the native browser initiated this paid acquisition.
The first harness assertion rejected a Markdown newline
between “revision” and “2”; correcting that assertion validates the same saved
answer/tool history without rerunning the model or source acquisition.

The final SIP browser run passes next/previous paging with exact clocks and
sequences, global descending sort and all 1,788 exported rows, and an interactive
43-row filter outside page one. An independent complete-result pivot returns
41,529 source units. Exports retain the same execution/hash and inspection
warning. Pinned widgets start no new executions and browser requests contain no
machine credentials.

## Verification and recovery

The final client suite passes 9,123 tests with 48 skipped. Application/table
ingestion type checks, browser build and unsigned arm64 build pass. The backend
immutable orchestration baseline collected 1,052 tests across 145 completed
groups, with zero failures/errors and three skips; installed modules are
qualified separately. The host release guards pass 34 tests with two explicit integration profiles
skipped when unconfigured. The final receipt fix passes 105 affected backend tests,
15 replay/schema tests and four packaging checks. This is baseline plus affected
verification, not a claim that the entire historical suite was rerun at the
final commit. Native MCP/SDK, reference, calendar and Security Master gates have
their own receipts. A genuine Python S3 mount host remains unavailable.

Final migration-044 cross-store recovery passed all ten protected examples.
The previous migration-043 snapshot already passed nine independent protected
replays. The new snapshot added the actual provider-backed explanation. Checks
compared original and replayed ordered rows/schema, independently verified each
archived runtime and established that the acquisition explanation remained
identical. Restore used new volumes and one
internal network per service, rotated bearer keys, preserved scope identities,
no provider keys and disabled acquisition. All actual service network attachments
were checked. The restore project is stopped after qualification; its volumes,
images and snapshots remain available. The source candidate restarted and
returned readiness 200. Tar extraction alone is not replay qualification.

The [execution decision ledger](EXECUTION-DECISIONS-2026-11-04.md) preserves
every recorded ruling and the earlier deferred minor. The committed native
browser acceptance harness is `v11/sip/widget-qualification.mjs`; it reads
server credentials only from its private mounted configuration.

## Explicit dispositions and remaining scope

* Whole-archive size, completeness, duplicate/order certification, canonical SIP
  session reconciliation and full migration remain operational follow-ups.
  Parent Milestone G permits bounded evidence; the v11 claim is formally narrowed
  to that inspection, not completion of every archive-inventory aspiration.
* Collector hashes establish retained-byte integrity, not independent provider
  authenticity or a signed source attestation. The full source Parquet was
  hashed, not archived into this sample's protected evidence.
* Historical listing membership and field-level bootstrap provenance remain
  outside the current-observed whole-package admission. Unknown business starts,
  publication history and CBOE MICs remain unknown.
* Live Yahoo, arbitrary provider integration, SQL-source inference and additional
  price bases are not qualified. Source-boundary tests do not prove every hidden
  SDK HTTP attempt is observable.
* Public TLS, an OAuth issuer, a signed/notarized application, registry publication
  and production cutover remain separate release operations. No framework rewrite
  or FastMCP/OAuth rollout is implied by authenticated scoped MCP tools.
* Native runtime images use verified wheel/bundle updates over qualified bases.
  A clean dependency rebuild failed NAS inode exhaustion; clean-build equivalence
  is not claimed. Dependencies and native Rust source bytes were checked before
  reuse. No unrelated volumes/images/services were removed.
* The independent reviewer did not inspect private artifact bytes or actual NAS
  network attachments and did not reproduce every historical suite. The local
  operator qualification records those checks separately. This distinction
  remains in the evidence even after recovery completes.
* A prior Security Master review's minor inventory-completeness suggestion stays
  deferred: native admission verifies all 22 required relations and fails closed;
  a more comprehensive standalone bundle-proof inventory is follow-up work.
* MinIO migration, vacuum/deletion, NAS OS/capacity changes and v11.5 portfolio
  analytics remain outside this candidate. Original SIP files and rollback
  targets are retained. Main and production selection remain unchanged.

For the basic data/receipt tutorial, start with `docs/guides/temporaldb-basics.md`,
`docs/guides/market-time-basics.md` and `docs/schema/README.md` in the TemporalDB
repository, then the [operator runbook](RUNBOOK.md); the individual
[reference](REFERENCE-RETENTION-QUALIFICATION-2026-11-03.md),
[calendar](CALENDAR-SOURCE-QUALIFICATION-2026-11-03.md),
[price](REAL-PRICE-POLICY-QUALIFICATION-2026-11-03.md) and
[SIP](SIP-INSPECTION-QUALIFICATION-2026-11-04.md) reports retain their narrower
source evidence and limitations.
