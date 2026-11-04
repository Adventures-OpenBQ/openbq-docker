# Retained reference responses: implementation contract

Status: next source-retention slice under the approved v11 NAS/reference roadmap.
This freezes the source audit; it does not claim installed retention or historical
identity coverage. Continue native execution under the user's keep-going instruction.

## Observed source

The isolated Security Master source e6888f365d1afdf9bcc9ac9516ebabd0a5e1a22f,
installed on the NAS, returned actual AAPL responses from
`POST /security-master/v1/odp/models/ReferenceSecurity/query` and
`ReferenceResolve/query`. Both return `{results, columns, extra}` where
`extra.security_master_receipt` has execution_id, request_id, kind,
temporal_mode, effective_at, known_at, availability_policy, projection_version,
dependencies, sql_fingerprint and created_at. Dependencies are relation names
with Delta versions, not TemporalDB catalog pins. Each result carries original
assertion_id/capture_id. Source receipts are written before the response returns.
Basic authentication is operator-managed access, not tenant isolation.

The real AAPL resolve response has null effective_from/effective_to. Its source
projection binds the admitted package fingerprint and visibility floor. These
facts support a retained current observation, not a verified historical interval.
ReferenceSecurity has no effective interval fields at all. Null CUSIP and missing
classifications remain null/unavailable; do not backfill them from unrelated fields.

An actual XNYS MarketCalendar request for November2–3 returned HTTP200 with zero
rows and dependencies at version0. This is **uncovered**, not proof of closure.
The separate qualified host calendar bundle is a rule-library source; retain its
own source identity and label its authority rather than pretending the Security
Master supplied sessions. Admit calendar material to the master only through an
explicit provenance-preserving source admission.

Private audit responses and SHA256 manifest are retained outside Git. No secret,
licensed source body or NAS credential belongs in this contract.

## Chosen boundaries

1. A strict versioned retained-reference envelope binds authenticated TemporalDB
   workspace/entitlement, source model/request/context, exact body digest, local
   capture/acceptance times, source receipt/dependencies and adapter version.
   Bound request/response size and finite JSON depth; refuse malformed/future
   schemas and inconsistent receipt contexts before analytical acceptance.
2. Preserve the exact source body as Bronze evidence. Validate its source
   receipt separately from the TemporalDB capture receipt. A source request ID
   is not a TemporalDB execution ID; a Delta version is not a catalog snapshot.
3. Normalize current-observed reference snapshots without manufacturing business
   validity. Store source effective bounds as nullable domain fields. Do not
   put capture/received/created time into a security mapping's effective_from.
   If the generic Fact representation cannot express this, use an explicit
   snapshot relation/contract rather than weakening domain date invariants.
4. Bind accepted reference publication IDs and content digests to execution
   inputs through an additive versioned manifest extension. Reads are scoped;
   corrections create new accepted inputs and preserve retained prior results.
   Past-local-knowledge queries cannot see data first retained later.
5. Calendar records must distinguish closed, uncovered, unavailable and refused.
   Preserve session/trade dates, zone, breaks, exceptions and source coverage.
   Existing timestamp and annual adapters remain compatible consumers, without
   granting annual envelopes richer coverage than their source evidence.
6. Price acquisition keeps the existing dated-identity requirement. Unknown
   current-observed mapping starts cannot authorize historical automatic prices.
   Explicitly report identity, calendar and price gaps separately.

## Verification gates

Actual AAPL source response round-trip; null-bound preservation; source receipt
versus local receipt separation; missing calendar rows remain uncovered;
wrong scope/context/dependency or digest refused; bounded parsing; corrections
and historical local acceptance preserve the original selected snapshot;
accepted reference IDs survive execution/replay and cross-store restore.

No provider/framework substitution, undocumented source-history estimate or
arbitrary timezone relabeling is part of this slice.
