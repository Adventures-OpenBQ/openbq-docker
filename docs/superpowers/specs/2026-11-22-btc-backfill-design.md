# BTC Day Chart backfill
Approved by user: use Coinbase for missing minutes. Fill missing completed BTC-USD minute bars only; preserve EODHD and recorded bars. Label Coinbase explicitly. Persist a bounded cache on the existing live-grid data volume, coalesce requests and avoid frequent history polling. Never write provider candles into the accepted tick tape. UTC session references and cumulative percent baseline remain unchanged. Failure preserves the current partial chart. Other symbols remain unchanged.

## Approaches
EODHD alone cannot currently supply today's missing minutes. Recording future ticks cannot reconstruct them. Chosen: genuine Coinbase BTC-USD candles for holes only, with explicit source attribution; exchange prices can differ slightly.
