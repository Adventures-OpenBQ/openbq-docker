# Retained SIP inspection implementation

Spec: `docs/superpowers/specs/2026-11-04-retained-sip-inspection-design.md`.
Native execution; one final whole-release reviewer. No original MinIO mutation.

### Task 1: freeze the collector and strict observation/matching contract

Files: H `v11/sip/` collector/profile/tests; P `temporaldb/sip/` parser/contracts/
row expansion and tests. Private actual source/corroboration bodies outsideGit.
- Write failing collector tests for fixed selected version/active file, bounded
  sampling/hash resources and evidence packing; implement against inspected APIs.
- Record exact collector/runtime/source profiles. Write failing P tests for
  request/body/hash/profile binding, naive timestamp preservation, exact UTC
  matching with no rounding, duplicate consumption, int64/binary64 fidelity,
  signed prices, exclusions and resource/schema/refusal cases. Implement pure
  parser, one observation Fact and bounded row expansion. No financial identity.
- Run focused suites and real source inputs; record matching/exclusion counts
  without attributing differences to an unproved cause. Commit owning repos.

### Task 2: accepted inspection Gold and explicit protected-audit boundary

Files: P registry/runtime/query/discovery/Gold/audit, additive043coordinator
registration/wheel/docs and integration tests. Freeze SQL before fixtures run.
- Write storage RED showing raw/Silver cannot become current inspection inputs.
  Add exactly the new registered Gold rule to fenced coordination; leave
  reference/calendar/current-price and D4 eligibility boundaries unchanged.
- Query expansion must retain matched-row order/position and domain flags;
  correction/input/scope tests must not expose stale rows or foreign scopes.
- Write audit RED: genuine qualified legacy inspection permitted; unknown or
  renamed legacy, SQL reinterpretation, incomplete captures and canonical tick
  claims still rejected. Validate retained snapshot proof inside the exception;
  archive all inspected/corroboration bytes and existing dependency closure.
- Verify real-storage projection/protection/replay and affected regression,
  regenerate schema docs, verify043wheel inclusion and commit.

### Task 3: client domain warnings and installed native inspection

Files: C temporal source/full-result consumers/tests as needed; H native
qualification docs/receipts. Private credentials stay out of code and evidence.
- RED then GREEN: partial inspection warning survives full-result loading,
  filter/sort/pivot/export and pin/copy. No live-current substitution or scope
  cache sharing. Keep query completeness separate from source-domain coverage.
- Build exact native P/C artifacts; back up owned config/stores, migrate/archive
  and retain real2048-row observation/1788matched subset. Verify raw hashes,
  accepted Silver/Gold, MCP and client rows/schema/receipts. Exercise >1000rows
  and filtering outside pageone using actual source rows. No synthetic demo.

### Task 4: final freeze, actual UI/Rita and shared recovery gate

- Combine with remaining parent widget/Rita qualification. Show actual widgets
  and a real Rita call using equivalent frozen execution identities/authorization.
- Freeze exact commits/images/config/source/runtime identities, protect bounded
  reference/calendar/price/SIP examples; consistent cross-store snapshot, restart,
  isolated restore and replay without live source access. Compare original
  rows/schema/hashes; preserve rollback target. Run final independent review,
  fix material findings by RED→GREEN and rerun affected gates.
- Update tutorials/runbook/release inventory. Do not claim canonical SIP analysis,
  live Yahoo sourcing, public TLS, signed app or production cutover unless their
  separate evidence exists. No merge/push/cutover inferred from a passing slice.

Review focus: inspection cannot masquerade as canonical Gold; no legacy-name
bypass; exclusions/originals remain auditable; UTC comes only from exact tuple
corroboration; raw naive timestamps and large sequences survive; complete-query
UI must retain domain-sampling warning; archived replay never contacts MinIO or
EODHD. Grade the bounded-inspection interpretation of parent Task5 explicitly.
