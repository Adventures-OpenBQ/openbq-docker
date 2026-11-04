# Bounded real daily-price policy implementation

Spec: `docs/superpowers/specs/2026-11-03-bounded-real-price-policy-design.md`.
Native execution under the existing keep-going authorization; keep source and
tracking claims separate. No per-task delegates or new approval loop.

### Task 1: source-bound one-day identity evidence

Files: H `v11/price-identity/` evidence manifest and bounded validation/export
helper; tests. Private full source bodies stay outside Git.
- Write failing tests for exact source hashes/CIK/venue/rename/date and refusal
  of changed bodies, provisional identity hidden as authoritative, or wider maps.
- Implement bounded validation and export only the existing five-field map plus
  evidence manifest/digest. Verify real retained inputs and preserve current
  Security Master unknown business dates. Run tests and commit source.

### Task 2: qualify the saved-policy miss and hit natively

Files: owned private qualification configuration/helpers and H evidence guide.
- Record frozen policy/account/map/source identities; back up changed config and
  retain old runtime. Install bounded mappings and archive their projection
  versions in the verified native image; no fresh-store bootstrap.
- Install restricted policy/grants. Exercise no-IO preflight, miss/run/accepted
  result, stable idempotency and cache hit with unchanged provider-call count.
  Refuse stale policy and outside identity dates before IO. Compare real raw
  hash and accepted execution; do not silently count a durable capture as done.

### Task 3: calendar linkage and release evidence

- Retain XNYS2025 for the selected date and preserve both execution references,
  session policy, price adjustment state and source/identity assumptions.
- Update data/tracking tutorial examples with exact bounded qualification.
- Carry the frozen artifacts to the shared final restart/restore/replay and
  actual widget/Rita gates; do not mark parent v11 complete at this checkpoint.

Review focus: the source-derived one-day assertion must not turn provisional
Security Master IDs into certified history; credentials never enter evidence;
cache reuse must require the same current policy/account/map identity; the
second run must demonstrate zero new acquisition, not merely equal numbers.
