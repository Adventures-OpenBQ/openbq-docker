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
The final collector snapshot SHA-256 is
`d2dbd54f92ac59aaae689dc4e451604a6a5294347d89a4333fd0676e48901349`.
The TemporalDB pure parser independently produced1,788 matched rows and260
unmatched positions. Signed prices and exact int64 sequences are contract-tested.

This is an inspection-only input. Enterprise security identity, canonical tick
eligibility, complete partition coverage and original publication time remain
unqualified. No source mutation, canonical tick analytics or full archive
migration follows from this result.
