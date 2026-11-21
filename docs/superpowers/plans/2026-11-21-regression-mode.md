# Regression Mode Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. V8 native checks continue independently.

**Goal:** Add an explicit isolated Compose regression launcher and qualify it on V9/V10 recipes.

**Architecture:** Canonical Compose JSON is transformed only for test isolation. Compose owns cached builds and volume initialization; a scoped lifecycle owns cleanup.

**Tech Stack:** Python standard library, Docker Compose.

**Spec:** docs/superpowers/specs/2026-11-21-regression-mode-design.md

## Global constraints and review focus

- New project and volumes each run; never delete foreign resources or prune images.
- Preserve normal volume initialization and unprivileged data ownership.
- Never resolve secrets into a persisted Compose model or receipt.
- Refuse shared mutable state, fixed ports and unsupported namespaces.
- A failed check/build/start must fail the run and still attempt owned cleanup.

## Task 1: Canonical model isolation and lifecycle

Files: create `scripts/compose-run.py`, `tests/test_compose_regression.py`; update README.

- [x] Write failing tests for fresh volume namespaces, writable-directory isolation,
  read-only binds, dependency closure, cached builds, verified prebuilt images,
  unsafe sharing refusal and cleanup after failing checks.
- [x] Run focused tests and observe failure because launcher is absent.
- [x] Implement `prepare_model(model, services, project)` and `main(argv)`.
- [x] Verify focused tests, complete repository tests and public-content scan.
- [x] Run two real fresh-container cycles proving empty state and UID ownership;
  change one build input and verify its output changes, then reuse it unchanged.

## Task 2: V9/V10 compatibility and carry

- [x] Resolve both published recipe models without loading private env files;
  verify selected API state is fresh and unrelated services remain excluded.
- [x] Record exact tested refs and preserve the wrapper for each later assembly.
- [ ] Use the flag in the full V9/V10 runs only after V8 is Ready.
- [ ] Commit the verified change and update the private release board/ledger.

One final launcher review completed. The two critical findings, ten important findings and two regraded input guards were fixed through RED/GREEN cases. All 60 tests and public-content scan pass; real init/build-only/retag/cancellation/private-output/literal-value checks pass. Full V9/V10 walk usage remains pending until V8 is Ready.
