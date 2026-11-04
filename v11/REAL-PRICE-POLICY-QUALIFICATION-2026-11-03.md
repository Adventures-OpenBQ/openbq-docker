# Bounded real-price policy qualification

The [native summary](qualification-2026-11-03/real-price-policy/summary.json)
records an actual EODHD XYZ.US daily-price workflow for January 21, 2025.
The [identity evidence](price-identity/block-xyz-evidence.json) and
[exporter](price-identity/BUILD.md) deliberately constrain the provisional
operator assertion to that one NYSE day. Security Master's unknown business
history remains unknown; this is not historical index membership.

Saved policy revision2 permits one symbol, one day and one 32 KiB request per run,
with no automatic retries. Its explicit acquisition credential is separate
from the existing MCP cache credential. The provider key is available only to
the worker. A read-only preflight indicated acquisition was needed; the
subsequent run retained the real response, accepted its normalization and Gold
publication, and produced an immutable execution. Raw OHLC and volume match the
113-byte provider response. A second preflight reported cached; a second run
returned the same rows with no additional provider operation, capture or budget
reservation. Duplicate submission returned the original run/execution. Stale
policy revision1 and the old credential's acquisition attempt returned403.
January22 was refused with DATE_NOT_ALLOWED before any provider operation.

Two reserved network attempts remain in the counters: the original isolated
worker could not resolve the provider, and its zero-retry run failed; after
worker-only egress and a verified fixed-provider TLS handshake, one explicit
revision2 attempt produced the sole accepted provider response. The failed
reservation was retained. API, PostgreSQL and object storage remain on the
internal network. No existing NAS service or SIP archive was changed.

The two receipt layers are distinct. Accepted Silver records
`runtime-normalizers-2:<identity-map-digest>`; the result records the Gold
`daily-v1` rule and exact source dependencies. The Gold row leaves adjusted
close unavailable because corporate-action dependencies are missing. Query
completeness does not imply adjustment completeness, portfolio coverage or
suitability for a factor model.

The initial preflight was asserted before submission but its raw JSON was not
retained after a qualification-helper assertion failed later. The accepted
run/publication/source bytes and final cached preview are retained, and the
summary explicitly records that evidence limit. The helper was resumed from
the existing accepted run; it did not repeat acquisition.

This is a bounded native data-workflow checkpoint. Calendar linkage, actual
visible widgets/Rita, bounded SIP admission and the final frozen
restart/restore/replay/review gates remain separate release requirements.

## Linked calendar and authenticated MCP checkpoint

[The production client verification](qualification-2026-11-03/real-price-policy/price-calendar.json)
binds the price execution and retained XNYS2025 calendar separately. It resolves
January21 to14:30–21:00UTC with `operational-v1`, records both input manifests,
source hashes and their common archived runtime, and preserves the provisional
identity and unavailable adjusted close. The provider made no live calendar
fetch while resolving the retained data.

[The local-knowledge check](qualification-2026-11-03/real-price-policy/calendar-local-knowledge.json)
returned zero eligible observations one microsecond before local receipt and
one afterward. This is local retained availability, not historical exchange
publication knowledge. [Authenticated MCP](qualification-2026-11-03/real-price-policy/mcp.json)
read the original price execution and produced a fresh cached execution with
the same rows, schema and result hash; its acquisition capability stayed denied.
The tutorial now explains both data layers and tracking layers with this case.
Final release/review, visible widgets/Rita and SIP admission remain open.
