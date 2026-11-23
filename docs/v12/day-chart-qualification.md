# v12 Day Chart qualification

2026-11-23. Parity port from the v10 implementation merged to main. No production deployment.

Day Chart supports CSV symbols and existing parameter/list resolution, independent Watchlist and Selected symbol groups, grid/scroll layout, one to five sessions, price or cumulative percent scale, day separators and per-day previous closes, hover, tile reorder and edge scrolling. BTC minute backfill and percent-baseline recovery are included. Layout controls and Selected symbol remain in the expandable Parameters panel; status and navigation remain in the footer.

Open **Example Dashboard - Version 12.0.0 - Day Chart** from the live-grid Apps catalog (or import `docs/examples/v12.0.0-day-chart.apps.json` from the v12 frontend). The Day Chart's `symbol` binds to Watchlist. Its `selected_symbol` binds to the separate Selected symbol group; the detailed Live Chart's `symbol` binds to that group. Input/output group reuse is rejected to protect the list.

## Verification

- Backend live-grid: 674 passed, 1 optional skipped, 14 network deselected.
- Gateway: 222 passed, including study proxy and Day Chart/logo routes.
- Frontend: 9,490 passed, 49 skipped; typecheck and lint passed.
- Web/policy/vendor tests: 127 passed. Production frontend build passed.
- Real local browser with actual v12 React app and FastAPI routes, deterministic synthetic OHLCV: clicking MSFT changed Selected symbol from AAPL to MSFT without changing AAPL,MSFT Watchlist; detailed Live Chart redrew 78 five-minute closed-session candles. Percent tiles rendered, and opening/closing Parameters exposed/hid row 1 controls.
- Independent integration review: no actionable issues; v12 study proxy, study editors, `ta_bars`, Art's Charts dispatch and chart adapter retained.

Market-provider continuity and physical touch behavior were previously qualified on the identical v10 Day Chart implementation. This port's browser check used synthetic data and does not claim a new v12 production or iPad qualification.
