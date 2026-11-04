# Bounded legacy SIP inspection

Run `collector.py` only with the fixed source/runtime profile in the collector.
The selected Delta version and active-file manifest, whole Parquet file SHA-256,
physical sample order, naive microsecond timestamps, binary64 price hex strings,
and decimal int64 sequences are retained. The source archive is read-only.

The reader image is the immutable qualified security-master image recorded in
`PROFILE` (deltalake 1.6.3, pyarrow 25.0.1). Supply the private TLS S3 settings via
an environment file. Do not commit credentials, private origins or raw licensed
responses. No insecure TLS fallback is permitted. The origin digest binds the
owned source without publishing its address.

The separately retained EODHD ticks response is corroborating evidence, not the
original archive receipt. HTTP framing and complete provider-window coverage are
not claimed. Only identical timestamp/sequence/binary64-price/size/venue/condition
multiset members qualify; duplicates consume one corroborating member each.
Unmatched originals are preserved, never repaired or called erroneous.

Native qualification on 2026-11-04: AAPL, partition 2025-01-21, Delta version1000,
one active file with 1,216,762 metadata rows, first2,048 physical rows sampled.
The collector snapshot SHA-256 is
`d2dbd54f92ac59aaae689dc4e451604a6a5294347d89a4333fd0676e48901349`.
The TemporalDB pure parser independently produced1,788 matched rows and260
unmatched positions. Signed prices and exact int64 sequences are contract-tested.

This is an inspection-only input. Enterprise security identity, canonical tick
eligibility, complete partition coverage and original publication time remain
unqualified. No source mutation, canonical tick analytics or full archive
migration follows from this result.

## Native widget acceptance harness

`widget-qualification.mjs` is the instrumented final browser test, not a source
collector. Run it only in an isolated qualification container using the pinned
Playwright/browser runtime and production browser bundle, application source and
host gateway mounts. It imports `/app/web` and `/host/funnel-gateway`; the exact
qualified runtime/image identities are in `../nas/qualification-2026-11-04.json`.
The container must reach only the selected qualification API/table services.

Supply `/private/harness.json` through a private read-only volume. It contains
server-scoped `apiToken`, `mcpToken`, `tableGatewayToken`, `tableRelayToken`, the
already retained `executionId`/`resultHash`, column names, exact `firstRow`/`lastRow` display values and independently
calculated expected sample totals. Never embed this file in a browser bundle or
commit it. Provide a separate writable `/output` volume; reports, raw exports and
screenshots may contain licensed source data and stay private. The test redacts
known machine keys and asserts that browser requests never carry them.

The harness creates a short-lived local self-signed HTTPS endpoint and synthetic
signed user session. These are test fixtures, not public TLS or OAuth issuer
qualification. It loads the actual retained result, tests next/previous paging,
global sort/export and a UI filter outside page one, records command/fetch
cancellation traces, checks viewport bounds and waits for a quiescent visible
result. It starts no new query executions. Native pivot and actual price-receipt
cases have separate evidence in the final qualification report.
