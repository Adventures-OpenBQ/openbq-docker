# v12 shared study qualification

Local first-slice qualification, 2026-11-22. No v12 deployment or production change.

## Delivered contract

`openbq_ta.studies.study` remains the single Python decorator registry. Its typed
parameter descriptors and loaded-definition identities feed the chart editor and
the live-grid column editor. The Arts service computes both through the existing
Polars pipeline; the grid does not implement RSI or stochastic mathematics.

The grid stores independent study/output/parameters, interval/session/basis/provider,
version and presentation settings in each column. RSI defaults to period 14 and a
latest value, rendered with the earlier centered-number 0–100 RSI meter: no fill
between 30 and 70, outward color below 30 or above 70. Its displayed integer is
rounded; sorting/filtering retain the precise server value. Slow %K explicitly uses `stoch`, `k=14`, `smooth_k=3`, `d=3`, output
`stoch_k`, with 60 displayed points. Displayed point count is independent of lookback.

`GET /study_catalog` and `POST /study_results` are available through the configured
live-grid proxy and exact gateway routes. Requests are batched once per second per
grid while quote streaming continues separately. Warmup is null; errors and changed
definitions are explicit per column. Provider-history inputs have null cursors;
they are not represented as accepted q tick inputs.

## Real HTTP qualification

An isolated, loopback-only fixture ran the actual Arts router/ComposedBars, actual
live-grid application/proxy and actual gateway over TCP. Its source generated
synthetic OHLCV bars; no market feed, user chart database, production service or
provider credential was used.

- Both catalogs matched, including an operator-loaded `@study` custom definition.
- Two symbols × RSI(14), RSI(7), slow %K(14,3,3) and custom study returned eight results.
- Direct and proxied values, points, definition versions and revisions matched.
- RSI periods produced independent results; slow %K returned 60 requested points.
- Invalid boolean/negative/unknown RSI parameters returned explicit column errors.
- Unauthenticated catalog access was refused.
- Gateway → live-grid proxy → Arts → shared Polars returned the expected RSI result.

The repeatable local drivers and their small result receipt are ignored under
`.superpowers/v12-studies/` (`serve_fixture.py`, `check_http.py`, `check_gateway.mjs`).
The fixture is deliberately not a deployable data source.

## Browser qualification

Chrome loaded the actual v12 browser-mode application against those real services.
The normal dashboard file/persistence seams were seeded with synthetic cards.

- Added RSI(14), then a second RSI(7): displayed 73.84 versus 87.71.
- Edited only the second RSI to period 9: displayed 82.59 while RSI(14) stayed 73.84.
- Added slow %K with explicit 14/3/3 settings: both symbol rows rendered sparklines.
- Saved settings survived application reload; persisted dashboard JSON retained each spec.
- The custom Python study appeared in both the grid editor and chart Series picker.
  Its declared period/scale controls were generated and the grid displayed its result.
- Removing the custom grid column and reordering the RSI columns preserved other values.

The minimal fixture omits the chart CRUD store, so chart-server persistence is covered
by repository tests rather than this browser fixture. Final typed-control UI and source
pin verification are recorded below when complete.

## Scope boundary

This qualifies the shared registry/editor RSI and slow-%K slice. Exact cursor-bound
VWAP/AVWAP and wiring the embedded Arts renderer to the accepted-candle model remain
separate milestones. The existing anchor behavior is preserved. Deployment configuration
and a decorator example are in [shared-study-columns.md](shared-study-columns.md).

## Final integration evidence

- HOST engine: 144 tests passed. Live-grid: 633 passed, one optional native test
  skipped and 14 provider-network tests deselected. Gateway: 217 passed, including
  termination of never-ending error bodies. Final vendor/profile/proxy checks: 12 passed.
- Arts source pin: `171d9732e951c410dbc2796b1784cc5dc53b0c00`.
  Vendored tree SHA-256: `22ac222439dbd6bcb0daecd85db88f30ffa0092b82cdeb401ba52225daf6f8f9`.
  Canonical client suite: 1,545 passed, one skipped; server: 1,051 passed, 62 skipped.
  Typecheck, build and Ruff passed.
- Repeated real HTTP checks against the final vendored server passed, including
  direct/proxy parity and the full gateway path. Python bytecode generation was
  disabled for the fixture so the source lock remains exact.
- Restored the existing RSI band renderer rather than inventing a new visualization.
  Chrome showed high-zone readings 83/74 and low-zone readings 17/26, with centered
  numbers and outward red/green fills; slow-%K sparklines remained visible.
  A real Chromium layout regression confirms nonzero meter width and centered labels.
- A deliberately outdated saved definition produced an explicit error without
  preventing current columns from rendering. Editing/saving against the current
  registry restored that column. Native and portable persistence, numeric sorting
  and filtering retain full values, independently of the rounded RSI label.
- Cross-worker peer review covered registry/version identity, service bounds,
  typed editor consistency, lifecycle, persistence and RSI layout. Important findings
  were fixed and rechecked before pinning. The untracked operator database and lock
  were not opened or modified.

The frontend's final full-suite/build results are reported with its implementation
commit; this receipt records the independently exercised HTTP/browser integration.

Final pin includes a header-only correction adding missing BUSL SPDX lines to three
canonical chart client files. Runtime behavior and the qualified server are unchanged.
