# Retained legacy SIP inspection slice

Continue approved NAS-roadmap Task5 after actual read-only inspection. This is
an inspection/quality-comparison data product, not canonical tick/session or
portfolio analytics. Preserve the original MinIO archive; no source vacuum,
copy-over, history rewrite or traffic cutover.

## Source facts and purpose

The original MinIO mount remains the ZFS29 archive. AAPL Delta version1000 has
the previously recorded active-manifest hash758a0477...; January21,2025 has one
active8,310,513-byte Parquet file with1,216,762 metadata rows. Its byte hash is
52d1a1bdbf6b1e1a306c7faf02a7596eebee7b0732f12283bb445f64f6e8ed6d.
The first2048physical rows were read without changing the source. Date is
Arrow timestamp[us] without timezone. The inspected deployed loader explicitly
converted epoch milliseconds as UTC before removing the timezone; its code
hash is retained. This alone is not a missing original provider receipt.

A separately retained, bounded current EODHD response for AAPL.US09:00:00–
09:03:13UTC contains2221prints.1788of the2048stored rows match timestamp,
sequence, exact binary price, size, venue and condition fields.260lack that
exact match; do not call these errors, repair them or silently drop their
original evidence. The comparison is hindsight inspection, not knowledge in2025.

## Contract

Use registered dataset `sip_archive.ObservedSlice`, representation
`legacy-sip-inspection-json-v1`, normalizer `runtime-legacy-sip-inspection-1`.
Keep the legacy labels visible. A protected inspection is an explicit audited
exception; renaming legacy data must never bypass the existing audit guard.

A fixed operator collector reads one explicitly selected Delta version and
active file, at most64MiB for hashing,4096sample rows and1MiB serialized snapshot.
It must verify the live TLS hostname, use private credentials, and refuse
arbitrary upstream/path overrides. Keep actual package/image/code profiles.
The snapshot retains every inspected original row, exact source-file/hash/
version/position/schema, and the exact bounded corroborating response bytes and
secret-free request/receipt. No original provider publication time is invented.

The request binds authority, source version, symbol, partition label, sample
offset/limit, source-file hash and corroboration hash. Scope comes from server
policy. Body/request/hash/profile/size/duplicate-key/nonfinite/precision checks
are mandatory. Strictly bounded integer arithmetic tests the UTC interpretation;
only exact full-trade tuple matches receive an interpreted UTC timestamp.
Preserve original naive values and binary64 prices, including signed prices.
Consume corroborating duplicates deterministically; unmatched originals remain
in Bronze and comparison diagnostics. No live IO occurs during normalization,
query, protection or replay.

Silver stores one source-qualified inspection observation, preventing stale
per-row leftovers. Gold's registered `legacy-sip-inspection-v1` rule selects
validated inspection observations only. Current queries require that accepted
Gold publication, not raw or arbitrary Silver. Dataset queries expand only the
matched subset into bounded, ordered rows, preserving original row positions.
Expose sample/source counts, unmatched count, inspection-only and partial-
partition flags, clock basis and `canonical_tick_eligible=false`. No enterprise
listing/issuer identity is fabricated from AAPL. This does not populate
`eodhd.ticks`, authorize a D4 complete-session group, or certify a daily bar.
Gold here means an explicit quality-comparison view, not complete market data.

Queries select retained/current observations; source business-effective and
provider-publication history remain unsupported. Captured local knowledge is
not original market availability. Keep the original captured bodies and exact
runtime/input dependencies for reproducible inspection. The dataset audit
exception must validate the exact registered dataset/representation/projection,
snapshot proof and mandatory inspection semantics. Unknown/renamed legacy,
canonical tick queries and arbitrary SQL reinterpretations remain refused.

The client must preserve partial-domain warnings even when every row of the
bounded query has loaded. Complete query result does not mean complete source
partition/session. A named saved example and metadata expose that distinction.

## Acceptance and scope

Pure source/matching tests; one real storage path through Bronze/Silver/Gold,
current vs unaccepted input authority, protected inspection/replay and existing
legacy-audit refusals. Then exact native artifacts with the real1788-row subset,
MCP/client agreement, paging beyond1000 and complete-result operations. Preserve
all excluded originals/diagnostics. Native restart/restore/replay is shared with
calendar/price at final freeze; actual widget/Rita and final review still gatev11.

This fulfills the bounded archive-inspection integration example. It does not
qualify canonical legacy-market-tick migration or full-session reconciliation.
If final review finds the parent release requires those stronger analytical
claims, leave that gate open; do not relabel this inspection as those claims.
