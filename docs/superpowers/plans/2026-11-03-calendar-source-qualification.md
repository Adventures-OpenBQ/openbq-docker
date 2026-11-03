# Calendar source qualification implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan natively. Steps use checkbox tracking.

**Goal:** Produce reproducible, hash-verified evidence of the installed v11 calendar source and include Security Master as the required identity/reference integration, before TemporalDB admits either source.

**Architecture:** Run an offline route harness against installed packages in the immutable provider-host image. Retain exact HTTP response bytes and a separately hashed qualification report. Existing calendar-core/route code is reused, not replaced by Security Master code from later branches.

**Tech Stack:** Python standard library controller; existing installed FastAPI/calendar packages; Docker with networking disabled.

**Spec:** Sibling TemporalDB `docs/superpowers/specs/2026-11-03-market-calendar-temporal-integration-design.md`, approved direction; source qualification precedes durable analysis integration.

## Global constraints

- Isolated existing v11 worktrees; no deployment, image rebuild, main merge or provider calls.
- Never call a library schedule exchange-certified, provider-published history or TemporalDB-accepted data.
- Pin image by full SHA-256 and compare installed source bytes with the checkout before trusting results.
- Retain exact response bytes separately from semantic calendar digest; bundle generatedAt is not local capture/acceptance.

## Review focus

- Closed-only request must remain explicitly closed in served coverage.
- Coverage clipped to supplier bounds is a gap, not a closure or complete coverage of the request.
- Unknown/reversed/oversized asks must refuse without a weekday fallback.
- Tampered/missing artifacts and escaping file paths must fail local evidence verification.
- Installed package/schema/source differences must be reported, not silently masked by host imports.

### Task 1: Evidence writer and integrity checker

**Files:** `v11/calendar_source_qualification.py`, `tests/test_calendar_qualification.py`.
**Interfaces:** `write_evidence(destination, report, responses) -> manifest`; `verify_evidence(destination) -> report`. No existing output may be overwritten. Bounded basename-only response identities, SHA-256 and byte counts.
- [x] Add failing round-trip/tamper/path/overwrite tests; observe red.
- [x] Implement writer/verifier and run focused tests.

### Task 2: Installed offline qualification and audit

**Files:** same controller; `v11/qualification-2026-11-03/calendar-source/`; `v11/CALENDAR-SOURCE-QUALIFICATION-2026-11-03.md`; TemporalDB tutorial/reference links.
**Interfaces:** CLI `--image sha256:<digest> --output <new-directory>`; subprocess runs only the installed calendar/route packages, mounting expected sources read-only. `--verify <directory>` checks retained bytes without Docker.
- [x] Exercise actual installed routes for capabilities, XNYS normal/holiday/early-close and DST, XHKG breaks, closed-only asks, refusal/resource limits and clipped coverage.
- [x] Validate actual bundles and inspect source/tzdata versions; demonstrate semantic digest vs receipt bytes and a synthetic correction without claiming a real historical correction.
- [x] Retain protocol evidence/report; run offline verification and existing core/client tests appropriate to the verified source contract.
- [x] Document source split, scope/knowledge limits and concrete next TemporalDB admission requirements; independent final review; fix findings and commit scoped work.

User steering: Security Master is part of the v11 foundation, not an optional
later-release alternative. Qualification of the installed calendar baseline is
one input to this integration; it does not replace or qualify Security Master.
