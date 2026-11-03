# Current-observed Security Master admission implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, honoring the user's existing native-execution choice. Steps use checkbox syntax. This is the subsystem contract required by roadmap task3, not permission to cut over production.

**Goal:** Admit the reviewed real S&P500 snapshot to the standalone Security Master without fabricating historical validity, publication times or classification support.

**Architecture:** Fix dated identity eligibility first. Build a deterministic, evidence-preserving admission package from the retained bootstrap, validate it in an unserved store, then qualify the immutable service artifact and deliberately select that store only within private NAS staging. TemporalDB's later reference bridge retains source responses and exact Delta dependencies separately.

**Tech Stack:** Frozen Python3.12 Security Master/Delta schemas and dependencies; source bootstrap DuckDB/Parquet plus1006 retained bodies; existing H image recipe and private NAS service.

**Spec:** `docs/superpowers/specs/2026-11-03-v11-nas-reference-data-roadmap.md`, domain/temporal ownership and release boundary.

## Work roots and file structure

H is the current isolated host worktree. The qualified source at `b4b7f4b68ae200f82b2067dd6ade70a9d425509a` was recovered as an immutable archive; it is not present as editable packages in H. Create S, a separate `codex/v11-security-master-admission` worktree at that source revision, beside H/C/P, using the donor repository's existing Git object. Do not edit the frozen archive, qualification environment, donor main or deployed image.

- S `security-master-api/security_master_api/resolver/identity.py`: dated identity eligibility.
- S `security-master-api/security_master_api/admission/`: validation, pure mapping and offline store admission; keep responsibilities in separate files.
- S `security-master-api/tests/test_current_observed_identity.py`, `test_sp500_admission.py`, `test_admission_recovery.py`: source/HTTP and interruption checks.
- H `v11/security-master/BUILD.md`: installed source/image/admission receipts and truthful limits.
- H `v11/security-master/provision.py`: only operator-owned staged store selection if an explicit root setting is needed; no credential forwarding or provider requests.

## Global constraints

- Preserve current-observed membership; a snapshot cannot establish past local knowledge or effective membership start dates.
- No seed CLI/golden fixtures on real stores; no source reacquisition or subscription changes during offline admission.
- Keep the qualified source dependency set separate from host OpenBB2 and TemporalDB DuckDB1.4.3.
- Preserve issuer/security/listing IDs already supplied by the reviewed bootstrap. Security Master becomes the single served domain master; the bootstrap remains source evidence.
- Preserve source-reported values and conflicts; CBOE's unresolved canonical MIC stays null. Source weights remain unrenormalized.
- The existing22relations have no classification relation. Retain classifications, weight and verification qualifications in Bronze evidence; do not advertise a normalized field or relation that does not exist.
- No production gateway switch, deletion, shared-store mutation or acquisition enablement. A failed admission must leave the selected empty staging store intact.

## Discovered source contract

`store.schemas.RELATIONS` defines22Delta relations. Silver interval fields include nullable `effective_from/effective_to`, `observed_at`, `available_at`, `system_from/system_to`, capture/assertion IDs/status/supersession. `store.tables.ensure` creates empty tables; `python -m security_master_api.store` seeds fixtures and is forbidden here.

The resolver's `identity._effective(row, at)` currently treats a null start as unbounded for an explicit date. The SQL interval filter already excludes null-start rows when an effective instant is supplied. Make identifier and stable-ID resolution refuse unknown effective history consistently. Current lookup without an effective instant can still return explicitly current-observed data. Preserve existing support for verified dated fixtures and closed aliases.

Set source capture time from the actual retained metadata. Set Silver `available_at` and `system_from` to the actual local admission time, not bootstrap build time or original provider receipt time. Keep unknown business-effective starts null. Do not reinterpret a Wikipedia date-added as a verified validity interval. For a Silver row with multiple dependencies, its observation time cannot precede the latest selected dependency. Retain the exact dependency selection in the admission manifest.

The reviewed package has503securities/listings/memberships,500issuer groups,2512identifier rows and1006source captures. `checksums.json` covers1016files, including source bodies and metadata. Accept a separately pinned checksum-manifest digest; reject path traversal, symlink escape, missing bodies, changed hashes, unknown input schema and timestamp-naive metadata before writing. Counts are reconciliation gates, not independent proof of provider identity authority.

Map issuer/security/listing IDs directly. The package has no instrument table: explicitly define one equity-share-class instrument per imported security, with a versioned UUIDv5 derivation from its existing security UUID. Do not merge instruments by issuer or ticker. Reject an existing populated destination rather than guessing how its IDs match. Share classes may share an issuer but must preserve distinct security/listing/instrument identities. This surrogate mapping is not an external identifier attestation.

## Review focus

- Missing effective history must not become an identity match for an earlier or arbitrary explicit effective date.
- A later import must not manufacture earlier local availability; known-at before admission must remain empty/unavailable.
- GOOG/GOOGL-like share classes must not collapse merely because CIK/issuer matches.
- A crash after some Delta appends must not expose a partial master or make retry duplicate data.
- Changed source bytes, unresolved MICs and absent classification schemas must not be hidden by a successful import count.

### Task1: Refuse unknown dated identity history

**Interfaces:** preserve existing resolver/HTTP request signatures; null-start current-observed identities are eligible only when no explicit effective instant is requested. Dated unknown-history refusal must be distinguishable from a successful current lookup.

- [ ] Add real temporary-store tests for current lookup, dated identifier lookup, stable-ID lookup, known-at before local admission and existing verified-date/closed-alias behavior.
- [ ] Observe the dated null-start test fail against the frozen source; change the smallest resolver eligibility/error path. Do not assign an invented start date.
- [ ] Run focused tests and the full238-test source suite plus the new tests. Expected: all pass. Commit the temporal guard in S.

### Task2: Build and validate the offline admission package

**Interfaces:** `prepare_admission(bundle, expected_manifest_sha256, admitted_at) -> AdmissionPackage`, containing schema version, mapping version, source hashes, exact dependency map and typed per-relation rows. It performs no store or provider IO except bounded local input reads.

- [ ] Test checksum/path/unknown-schema rejection, source timestamp handling, direct IDs, deterministic instrument IDs, distinct share classes and unresolved MIC preservation; observe missing implementation RED.
- [ ] Implement pure mapping into actual declared schemas. Retain Bronze source payloads and the original classifications/verification/weight evidence. Require timezone-aware admission time and nonfabricated source times.
- [ ] Validate the real reviewed bundle offline: reconcile503/500/1006 counts, join integrity and all source hashes. Expected: explicit report including unsupported fields; no destination write. Commit source/tests and H contract clarification if necessary.

### Task3: Admit into an unserved store with recovery evidence

**Interfaces:** `admit(package, new_destination) -> AdmissionReceipt`, recording package/source/mapping digests, relation versions/counts and completion marker. Only a completed, reconciled receipt can authorize operator selection of that destination.

- [ ] Add interruption tests before first append, mid-relations and before completion marker; observe RED. Selected staging root must remain unchanged throughout.
- [ ] Implement bounded writes to a new admission-specific directory/volume, with immutable input identity and explicit incomplete/completed state. Retry either validates the exact completed receipt or resumes safely without duplicate appends; never silently overwrite a populated unrelated store.
- [ ] Run real offline store/read tests, hash reconciliation and source suite. Expected: no partial master selected, exact IDs/counts/provenance retained. Commit.

### Task4: Qualify the updated installed source and private NAS selection

**Interfaces:** exact new source archive/image IDs, installed qualification log, admission receipt and authenticated reference responses with Delta dependency versions.

- [ ] Build from the new clean S source/archive with H's frozen recipe. Run the entire installed suite offline natively on NAS; the prior1092c5a3 runtime is not proof of the changed code.
- [ ] Admit the real package into a new unserved NAS destination. Verify all hashes/counts first, then recreate only the private staging service using that completed destination and new immutable image.
- [ ] Query a real ticker and ISIN; verify two share classes, ambiguity refusal, null-MIC qualification, explicit dated unknown-history refusal and known-at before admission. Restart and repeat exact version/provenance checks. No provider calls.
- [ ] Record source/image/runtime/admission identities and limits in H. Retain the former empty store/image. Obtain the roadmap's independent release review before any production cutover; a successful private admission does not satisfy the later TemporalDB bridge/restore gates.
