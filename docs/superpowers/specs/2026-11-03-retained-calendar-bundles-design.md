# Retained calendar bundles: bounded v11 slice

This implements step4 of the approved retained-reference plan and the approved
dated-calendar direction. Execution remains native under the user's keep-going
instruction. Builder calls below are implementation decisions, not new user
requirements. The broader price, SIP, installed-widget and Rita gates remain.

## Existing source and approach

H's `calendar-core/openbq_calendar/contracts.py` defines CalendarBundle v1;
`canonical.py` hashes canonical content excluding digest and generatedAt.
H's `v4/routes/openbq_routes/calendar_v1.py` serves
`/api/v1/calendar/trading/v1/bundle?calendar_id=...&start=...&end=...`.
It returns whole-year coverage, sometimes clipped to supplier bounds. The
qualified source has 71 calendars, exchange_calendars4.13.2 and tzdata2026.5.
Its existing qualification image0820fc93 is **arm64**, as freshly inspected;
it is not NAS deployment evidence. Build and test a native amd64 source artifact.

C already has strict bundle verification, sharedBundleCache,
createBundleProvider, prepareCalendarBatch and resolveCalendarFields. Reuse
these seams and the existing operational-v1/planning-v1 policies. The current H
v11 TA tree has no regular_only implementation; do not transplant that function
from a later donor branch or claim its consumer alignment.

Alternatives: extend the annual-hours envelope (loses dated breaks/coverage);
introduce another calendar format (duplicates the reviewed protocol); retain
the existing rich bundle (selected builder approach). P remains standalone:
vendor only the Apache-2.0 source validation/canonical modules with origin
hashes, rather than adding an OpenBB/provider dependency. P's wrapper adds
boundedness and client-compatible UTC precision checks.

## Source collection and admission

Register `calendar_source.CalendarBundle` for explicit collection, accepted
Silver observation queries and local-known_at history. No calendar Gold rule,
provider-publication history or automatic acquisition grant is implied.
Request identity: source_authority, source_mode=current_corrected,
calendar_id (canonical exchange identifier), start and end ISO dates. Bound
requests to366 inclusive days, responses to1MiB and at most732 served days.
Whole-year excess coverage is allowed and retained. Actual served coverage and
requested coverage are separate; clipped coverage is partial, not closure.

A bounded fixed-origin collector reuses the existing framed HTTP transport.
Security Master and calendar credentials must remain distinct if both sources
are configured. No redirects, discovery IO or credentials in capture evidence.
The native source wrapper serves the existing route with private authentication
and PYTHONTZPATH empty, forcing the pinned tzdata package. Record that actual
environment and source hashes; a package label alone is insufficient evidence.

Accept only this qualified library adapter's library_baseline days in this
slice. Preserve the exact raw bundle, byte hash, semantic digest, generation
clock, rule/source/tzdata versions and requested/served bounds. Generation time
is not local receipt, acceptance or provider publication. Reject duplicate JSON
keys, malformed or overprecise UTC, forged digests, unsupported authority claims
and partial transport. One observation per full source-qualified lookup prevents
old per-day rows surviving a corrected or clipped bundle.

Reuse capture/assertion/publication/source-vector authority. Add migration042
to admit only runtime-calendar-observations-1 accepted Silver, with the same
single-statement catalog ambiguity/selection rule as041. Existing reference
eligibility and price Gold requirements remain. Business-effective query modes
do not reinterpret lookup observation time as session history; select a retained
bundle with current, snapshot or local-known_at, then resolve its dated days.

## Resolution and consumers

P provides session lookup/membership over retained validated UTC segments;
require the existing policy explicitly. Closed, unresolved and uncovered are
different. For continuous observations only, use explicit half-open segments;
this does not define auction membership. Preserve date-only labels unchanged.

C adds a retained-result adapter into createBundleProvider using the shared
cache. Verify the exact raw bundle hash and semantic digest, selected execution,
context and input identity; scope/cache identity includes those frozen inputs.
Retained reads never fetch a live calendar or fall back. Return the retained
reference alongside prepared batches so assumptions and provenance remain
available. Exercise the same early-close, DST, break and gap cases in P and C.
Library baseline is always labeled as such, never exchange certification or
proof of what was known before capture.

## Acceptance

RED→GREEN adapters, transport isolation, retained corrections and prior-known
selection; client/server conformance; generated docs and exact wheel resources.
Then actual amd64 source→capture→Silver→execution→client provider and MCP,
with restart/replay/restore evidence from exact artifacts. Source tests, the
earlier arm64 source harness, and parser-only acceptance do not complete this
gate. No main/push/cutover or SIP-source mutation is authorized by this slice.
