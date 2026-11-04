# Retained calendar bundles implementation plan

> **For agentic workers:** Use superpowers:executing-plans natively, preserving the user's execution method. One whole-release fresh review remains at final freeze.

**Goal:** Retain qualified rich calendars and resolve the same dated inputs in P and C.
**Architecture:** Existing CalendarBundle v1 → bounded explicit capture → accepted Silver observation → exact execution → existing client calendar-provider seam.
**Tech Stack:** P Python/Pydantic/PostgreSQL/DuckLake; H pinned calendar-core/FastAPI; C TypeScript calendar protocol/cache.
**Spec:** `docs/superpowers/specs/2026-11-03-retained-calendar-bundles-design.md`.

## Global constraints

- Existing isolated P/C/H worktrees; no copied later donor TA implementation.
- Existing operational-v1/planning-v1 and CalendarBundle v1; no invented wire API.
- Library-baseline authority only; explicit UTC≤6fractiondigits, daily labels stay dates.
- 366 inclusive requested days,732served days,1MiB bytes; source/current/local knowledge clocks distinct.
- No hidden collection, fallback, provider grants, Gold calendar rule or source-history claims.
- Keep041 unchanged.042 candidate validation and selection share one SQL statement.

## Review focus

- Identical calendars with different scope/context/execution cannot share mutable cache owners.
- A clipped latest bundle cannot expose stale day rows from a prior complete bundle.
- Two configured sources cannot accidentally share the last configured Basic credential.
- A declared timezone package must match the active source timezone backend.
- A successful capture acknowledgement must not be mistaken for accepted publication.

### Task 1: strict observation adapter and bounded session resolution

Files: P new `temporaldb/calendars/{contracts,canonical,observations,sessions}.py`, origin receipt and `tests/test_calendar_observations.py`; qualified real source fixtures under `tests/fixtures/calendar/`.
Interfaces: `parse_calendar_response(scope,parameters,body,received_at)` → immutable observation; `calendar_facts(observation)` → one Fact; `calendar_lookup_key(parameters)` → exact authority-qualified key. `resolve_session(bundle,day,policy)` returns distinct open/closed/unresolved/uncovered; `contains_instant(session,instant,boundary='continuous_half_open_v1')` requires aware UTC and respects breaks.
- [ ] Add imports/real XNYS/XHKG/clippedXSHG tests; first run must fail missing adapter. Test Nov26closure,Nov27earlyclose18:00Z, winter/summer UTC opens, XHKGbreaks, clipped unknown, duplicate keys, digest/precision/authority/resource refusals.
- [ ] Vendor exact174+12line Apache validation/canonical sources and record source hashes. Implement bounded wrapper, one observation Fact and pure resolution; include declared source clocks/coverage.
- [ ] Run `pytest tests/test_calendar_observations.py -q`; expected all pass, then commit the independently testable adapter.

### Task 2: explicit collection and retained publication authority

Files: P `temporaldb/calendars/capture.py`, existing acquisition/registry/discovery/runtime/query runner, new observation-key dispatch helper, `migrations/042_calendar_input_vectors.sql`, pyproject wheel map/docs; tests `test_calendar_capture.py`, `test_calendar_retention.py`, existing atomic/source regression tests.
Interfaces: `CalendarCollector.collect_current(scope,parameters)` → CaptureEnvelope; dataset `calendar_source.CalendarBundle`; projection `runtime-calendar-observations-1`. Current query exact key dispatch supports existing security_master models unchanged.
- [ ] Write failing tests for fixed GET route, no IO before explicit call, two-provider credential isolation, partial/oversized response refusal, and scope before IO.
- [ ] Implement per-provider private source settings in existing framed transport; add bounded request validation and collector.
- [ ] Write failing real-storage test: original/corrected/clipped bundle retains raw hashes, accepts only scoped Silver, does not queue Gold, selects exact/current/local-known_at inputs and refuses effective_on/source publication history. Add calendar to atomic catalog-selection/mixed-source regression.
- [ ] Register/normalize/query the source with042; regenerate docs and verify wheel SQL/resources. Run `pytest tests/test_calendar_capture.py tests/test_calendar_retention.py tests/test_reference_response.py tests/test_reference_retention.py tests/test_reference_input_atomicity.py -q`; expected pass. Verify acquisition HTTP tests separately from shared fixture-budget tests. Commit coherent source.

### Task 3: retained client provider and shared conformance

Files: C new `src/lib/calendars/retained.ts` and test, existing provider/cache only where necessary. P/H/C common source-based case receipt. C `src/lib/temporal/client.ts` and test own MCP-compatible default paging.
Interfaces: `createRetainedCalendarProvider(selection,cache)` consumes exact validated ResultPage + backend/scope identity and returns existing CalendarProvider plus retained reference; no live fetch. Selection includes frozen execution/context/input identity; bundle byte/semantic hashes verified.
- [ ] Write failing tests for real retained bundle, altered bytes, scope/context/execution separation, earlyclose/break/DST/date-label parity, clipped-gap refusal and old retained selection after correction.
- [ ] Add a RED assertion that new Cclient executions default to100rows/page (MCP cap), preserve explicit1000 HTTP overrides, then change only the default. Keep old retained execution semantics.
- [ ] Implement using existing shared cache/verifyBundle/createBundleProvider; preserve operational/planning policy vocabulary and expose retained reference for prepared batches.
- [ ] Run focused calendar/temporal contract tests and typecheck; expected pass. Commit with the backend source contract receipt.

### Task 4: native source and installed end-to-end qualification

Files: H `v11/calendar-source/` minimal source wrapper, locked dependencies/build recipe/qualification helpers/tests and updated evidence guide.
- [ ] Add failing source-config/Basic/auth/readonly/no-arbitrary-upstream tests; implement wrapper around existing route, with pinned tzdata backend and bounded configuration.
- [ ] Build exact amd64 source+P artifacts; preserve source/image/recipe/profile identities. Start only owned isolated services and explicitly collect real XNYS/XHKG/clippedXSHG bundles.
- [ ] Verify accepted capture, exact/current/local-known_at result, client existing provider/resolution and MCP parity, then correction/replay/restore. Separate source status, coverage and identity from real price coverage. All expected tests/results must pass before claiming calendar installed acceptance.
- [ ] Update both data/tracking tutorial tracks and the reference-plan ledger; continue dated-price/SIP and visible-widget/Rita gates. Native checkpoints do not authorize a main merge/push/cutover.

Self-review: task1 defines data/grain consumed by2; task2 defines dataset/version/execution consumed by3; task4 qualifies both rather than treating an arm64 harness as NAS proof. All five review classes have explicit task tests. No new acquisition-policy or canonical run-request fields are introduced in this bounded calendar slice; price+calendar joint workflow coupling remains a separately reviewed next step.
