# Release v4 calendar integration (draft)

This is the release/v4 implementation increment, before a forward walk through later releases. It does not change or merge release branches.

## Delivered

- Independent Apache-2.0 `openbq-calendar` 0.1.0 package with validated v1 bundles, content digests, an explicit exchange registry, actual per-day sessions and intraday segments.
- Legacy trading-calendar response remains available through a compatibility adapter. New routes are `/api/v1/calendar/trading/v1/calendars` and `/api/v1/calendar/trading/v1/bundle` (`calendar_id`, `start`, `end`). The Dockerfile builds/installs both calendar and route wheels with existing locked supplier dependencies.
- Client validates and hash-checks bundles, freezes a batch reference instant and bundle vector, and resolves the existing expression grammar over retained sessions. Joint date bindings support all-open/any-open. The FX helper composes explicitly supplied payment IDs; no payment calendar feed is supplied here.
- Manifest widgets may opt in with `calendarBinding` and `calendarResolutionPolicy`. Direct `fetchWidgetData` calls prepare all typed expression fields before issuing the widget request, pass literal values through `wireParams`, and expose client evidence via `WireContext.onCalendarResolution` and `useWidgetData.calendarResolution`. Cancellation aborts calendar transport and prevents late hook publication. Unavailable selected calendars block submission.

Example widget opt-in:

```json
{"calendarBinding":{"schemaVersion":1,"kind":"single","calendarId":"exchange:XNYS"},"calendarResolutionPolicy":"operational-v1"}
```

## Scope and limits

Only exchange schedules from exchange_calendars 4.13.2 are advertised. Their evidence is `library_baseline`, not exchange-certified final authority. Trading calendars do not imply bank holidays, payment eligibility, settlement conventions or FX value dates. No central-bank/payment feed, automatic cross-to-calendar mapping, settlement lag or cutoff rule is implemented. Taiwan v1 history before 2019 is refused; Tokyo capabilities begin in 1997. Legacy compatibility semantics stay distinct.

This draft is not a full completion of the approved Project 1 plan: discovery selection UI, parameter/dashboard binding precedence, native/apps export round trips, QueryBuilder/linked-table/TemporalDB-specific consumer wiring, attached dataset/export provenance, browser end-to-end qualification, rollback and Python3.12 image qualification remain pending. DateProbe uses its existing legacy path. Do not enable the opt-in broadly until those gates are complete. No TemporalDB code or migration is included.

## Evidence (2026-10-23)

Host PR base: `6db686f69657fcf61881af8609fe9a22a9f685e6` (stale local tracking base `af0c8a3` was corrected by merging the target into the feature branch before final delivery). Client base: `4fd41cd217e7b955e738aafcedc6e44008452359`.

- Host focused supplier/contract/FastAPI route tests: **19 passed**, including against wheels installed into an isolated temporary target.
- Built calendar wheel SHA-256: `97379e3a92ab827c414b67979122ddf59d96faadde7490f697652f56c225fac3`.
- Built route wheel SHA-256: `7620aed6c024d047dc40d33dc51b6b045dde342ca9482137885d6c7588cbf216`.
- Native qualification environment: Python3.13.0, exchange_calendars4.13.2, pandas2.3.3, pydantic2.13.4, tzdata2026.2, OpenBB core1.6.13. This differs from the Python3.12 Docker target and locked pandas3.0.6/pydantic2.13.5/tzdata2026.5/OpenBB core2.0.1. Container qualification is pending; native test results do not qualify that target.
- Full host `pytest` attempted: collection fails in `examples/episode3/test_reference.py`, `provider-fixes/tests/test_core.py`, `provider-fixes/tests/test_finra.py`, `provider-fixes/tests/test_warnings.py`, `v3/econdb/tests/test_econdb.py`, `v3/videos/source/tests/test_router.py`, and `workspace/tests/test_assembly.py` (missing legacy/provider modules, test-module collision and assembly prerequisite). These are outside the calendar-focused passing suite; the complete host suite is not green.
- Client focused core/legacy tests: 225 passed before transport additions. Real HTTP transport + existing data-client/calendar/widget hook suites: 188 passed. Further review regressions cover data bounds, mixed fractional timestamp precision and property-name field IDs.
- Contract artifacts were re-exported from this supplier and vendored with SHA-256 verification; the vendoring tamper/atomic replacement test passed.
- Correct release/v4 Pivot WASM built from its source using Rust1.98.1 and wasm-bindgen0.2.128; smoke test passed. Client typecheck, changed-file ESLint and production Vite build pass (existing chunk-size/dynamic-import warnings).
- A fresh reviewer checked both repositories; both identified issues received failing regression tests and fixes. Full-suite final result is recorded separately below.

Full client final run: **355 files passed, 2 skipped; 6,402 tests passed, 7 skipped**. No failing tests.

## 2026-10-23 review fixes

- All nine calendars carry conformance fixtures whose facts `calendar-core/tests/test_qualification.py` checks; the registry advertises exactly that set, and capabilities report the supplier's own bounds inside 1990–2040 (Taiwan from 2019 by qualification).
- Bundles are built for whole years and cached as bytes under a 64 MB budget; capabilities are built once in a worker thread.
- Route tests mount the v1 routes without openbb-core, so they collect on the host.
- Still open: `openbq_calendar/legacy.py` remains a second generator for the v3 envelope; Security Master is absent on v4; container (Python 3.12 image) qualification and a rollback note are not done.

## 2026-10-24 full calendar set

- `calendar-core/openbq_calendar/catalogue.py` generates `resources/calendar-catalogue.json` from exchange_calendars 4.13.2 plus the curated names and suffixes in `curation.py`; a test regenerates it byte for byte. `CALENDARS`, capabilities and bounds read it: 71 calendars.
- Bounds are what the library covers inside 1990–2040: AIXK from 2017, XBOM 1997–2026, XSAU 2021–2029, XSES to 2026-12-31, XSHG 1990-12-03 to 2026-12-31, XTKS from 1997, XTAI from 2019 (qualification). XBOM, XSES and XSHG therefore stop at 2026-12-31 until a library upgrade extends them.
- `calendarId` admits the library's names (`exchange:24/7`, `exchange:us_futures`): pattern `[A-Za-z0-9_/-]+`. Bundles and routes clip whole years to each calendar's bounds.
- Qualification: a 2026 snapshot per calendar (`calendar-core/tests/snapshots/`, library_baseline, tied to the catalogue digest) and hand checks for XPAR, XETR, XSWX, XSHG, XKRX, XBOM, XSES, BVMF, XMEX, XJSE, XASX and CMES (Sunday-evening open).
- Suffix sources: EODHD's published list (63 rows, read 2026-10-24) plus the 2026-10-23 rulings; Yahoo's help page SLN2310. Dropped suffixes, with reasons, are in `UNMAPPED_SUFFIXES`; `.NX` (Euronext as one venue) is the one cross-calendar ambiguity. EODHD codes JSE, SR, BSE and LU are not on the published list and are left unmapped as unverified.
- Library disagreements found, not asserted: XKRX 2026-06-03 (local-election day, normally a KRX closure) is an open session; SGX's Christmas and New Year's Eve half days (2026-12-24, 2026-12-31) are full sessions; XJSE 2026-11-04 (South Africa's local-election public holiday) is an open session (found in the Task 3 review).
- Coverage limits in exchange_calendars 4.13.2: XBOM, XSES and XSHG end on 2026-12-31; XSAU ends on 2029-12-31.
- Hand-check verification (Task 3 review): 11 of 12 checks verified against sources, several from secondary sources only (XSWX, XKRX Feb 17 and Sep 25, XBOM, XSES, XMEX, XJSE, CMES, and the XPAR half-day time). XKRX 2026-12-31 closure is still unverified: KRX announces the year-end closure each December, so re-verify when the December 2026 notice is published.
- Rulings: Q1 widget/param `exchange` keeps catalogue ids (`canonicalCalendar(v) ?? v.toUpperCase()`), so `us_futures` stays `us_futures`. Q2 the menu search box closes on Escape. Q3 the `calendar_v1.py` docstring's last sentence is rewritten, not exact-replaced. Q4 Task 4 Step 1 covers ten existing fixtures, not nine (`XNYS-2026-12.json` included). Q5 the new-test count is 85 (71 + 12 + 2), not 83. Q6 bounds follow the spec's own rule ("the range the library actually covers"); the spec's "to 2040" figures were wrong, and the shorter XBOM/XSES/XSHG/XSAU coverage was reported to the user on 2026-10-24; snapshots live in `tests/snapshots/`; cost: three markets show coverage errors from 2027 until a library upgrade. Q7 a subshell `(cd "$OD" && …)` is allowed because it cannot change the caller's cwd.
