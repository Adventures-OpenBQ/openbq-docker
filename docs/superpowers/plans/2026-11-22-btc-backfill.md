# BTC Backfill Implementation Plan
> Implement inline using superpowers:executing-plans.

**Goal:** Fill BTC Day Chart missing completed minutes using Coinbase.
**Architecture:** Dedicated bounded persistent candle cache; gap-only merge before DayCharts formats sessions. Existing history/ticks win timestamp conflicts. No accepted tape mutations.
**Tech Stack:** Python, httpx, JSON atomic cache, React/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-22-btc-backfill-design.md

- [x] Test gap-only merging, validation, dedupe, UTC bounds, cache restart, coalescing, cooldown, provider failure and request budgets.
- [x] Implement BTC-only backfill helper; wire into crypto Day Chart history. Keep unavailable data partial.
- [x] Test/render explicit Coinbase source attribution; update help.
- [ ] Run backend/frontend checks; publish exact source and deploy existing backend/frontend.
- [ ] Verify actual completed-minute continuity and BTC selection into detailed chart; retain rollback evidence.

Review rulings: pace Coinbase starts at 150ms (under seven per second); 60s retry cooldown; reserve five seconds of the tile budget for daily reference/metadata and return existing bars if fallback times out. Successful chunks remain in memory if another chunk fails.
