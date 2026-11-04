# v11 execution decisions and deferred review items

Verbatim rulings from the execution ledgers, grouped by owning plan and kept in ledger order. Early progress wording is historical; the final qualification report supersedes it. Each line preserves its reason, cost or acceptance boundary. These are decisions made while implementing the approved plans, not new authorization for publication or cutover.

## BDOBB widget and acquisition plan

* Ruling: Keep the current isolated worktrees and branches, retaining exact baseline commits and artifacts — isolation already exists; no redundant worktree — costs review range tracking.

* Ruling: Add a 2 MiB validated page-admission bound in the pager in addition to row/history limits — prevents oversized page activation; transport streaming budget will be assessed with managed admission — cost is typed refusal of unusually wide pages.

* Task 2: Ruling: Page offsets/page numbers are additive provenance fields only on pager-owned input — original source adapter export metadata stays compatible; installed export harness must accept the additional fields in Task 9.

* Task 3: Ruling: Reuse the existing authenticated retained execution pages API instead of adding a duplicate table-source API — it already enforces scope and retained result identity; trusted server ingestion exhausts pages under strict bounds — costs one request per page, without introducing another read authority.

* Task 3: Ruling: Reuse admitted backend bindings with a new temporalExecution response kind; propagate authenticated catalog-lease principal to the private ingestion child, and select only operator-configured per-principal TemporalDB headers — avoids a new source catalog format and credential forwarding from browsers — omission must deny before network access.

* Task 3: Ruling: Add version-1 tableExecution routing metadata to query bindings and preserve it on pin — enables one query widget to select managed complete-result semantics; old bindings stay page-local — cost is explicit connection selection until Task 8 UI/discovery wiring.

* Task 3: Ruling: Advertise sourceReceiptWire during managed session opening; validate it before accepting a temporal session and use it directly for widget receipts — avoids downloading whole chart rows merely for metadata — costs a bounded optional protocol field.

* Task 4: Ruling: backend changes use backend base ad37d75eff134bfd7d52c45be4fc88529b9cd14e; primary ledger/task scripts stay with the client plan. Record both repository commits explicitly because commit ranges cannot cross repositories.

* Task 4: Ruling: provision policy management in a DB-owner-only manager table and expose read-only public discovery first — management grants cannot be supplied by browser requests or policy bodies; run permission remains a distinct Task 5 authority.

* Task 5: Ruling: keep API/worker database identities separate. A narrow job-fenced worker finalizer will call the existing execution_start internally and attach the resulting execution ID atomically to the run; no general API-role privileges or raw API tokens are given to workers. This avoids duplicate execution creation after retries while preserving existing manifest/60-second execution guards.

* Task 5: Ruling: reuse existing DeferredOutcome/typed-job selection (already supports arbitrary job_type selection); do not alter migration 032 or lease retry semantics.

* Task 5: Ruling: provider-operation sharing remains at the existing scoped acquire_response seam in Task 7; each caller intention has its own driver job — cancellation cannot cancel another caller's intention; sharing must include provider account and acquisition identity when transport is connected.

* Task 5: Ruling: include migration 033 as well as 034 in wheel packaging — the packaging regression test exposed the existing omission; without it an installed service would lack saved policies. No dependency versions changed.

* Task7 Ruling: share provider operations only within identical workspace/entitlement/principal/account/policy-ID/revision/request. Existing account seam does not distinguish policy revisions, so add a worker-only fenced run reservation while preserving its provider job/capture/account protocol. Cost: conservatively duplicates requests across different policies instead of assuming compatibility. Provider operations keep their own lease independent of caller cancellation; retries of reservation return pending rather than reauthorizing a second fetch. Byte/retry accounting, transport and dispatcher still pending.

* Task7 Ruling: expired/unacknowledged attempts consume their reserved byte cap unless an exact retained response size is known; keep retiredattempts in durablehistory and do not refund uncertainIO. Costs conservative earlier budget refusal after a crash. Providerattemptlease90s bounds uncertainowner recovery within the existing300s default run deadline; no physicalfetch is reauthorized by ordinary reservation retry.

* Task7 Ruling: managed Yahoo currently qualifies only explicit raw daily equity-history semantics (auto_adjust/prepost/repair false); other semantics remain refused until coverage keys distinguish them. This avoids reusing one price basis for another; cost is narrower automatic acquisition. SDK output remains sdk_decoded_v1, and oversized/incomplete SDK output has its own unaccepted prefix representation without HTTP metadata. NativeNAS SDK artifactb837a2a4 built and network-off/nonroot importsmoke passed; combined TemporalDB artifact/actualflow stillpending. Hrecipe28f2739 records separatevenv build and unchangedP dependencies.

* Task 8 Ruling: use the canonical AcquisitionRunRequest shape for a read-only preflight, requiring already frozen typed parameters and returning submitted=false/provider_called=false — avoids accepting client-supplied account/catalog/version authority or silently choosing a second relative clock. Preview creates no job and reserves no future coverage; submission rechecks authority. Cost: callers resolve relative expressions before preview and must not treat preview as a guarantee.

* Task 8 Ruling: new acquisition executions use100-row retained pages through additive039, shared by widgets and boundedMCP — MCP must never slice1000-row pages and return a cursor that skips900rows. Older retained executions retain their original page contract and may be refused byMCP when oversized. Cost: more requests for widget paging. Additive040 expands metadata-only audit names; no new runtime table privileges.

## NAS roadmap

* Task 2: Ruling: retain actual deployment receipts outside Git — they contain private infrastructure topology even without credentials; commit tooling, tests and explanatory status only — cost is separate private-artifact retention responsibility.

* Reference Ruling: use existing accepted Silver publications/pins for lookup observations instead of a new canonical manifest extension — existing audit/replay authority already retains exact raw captures and interpretation versions — costs that these datasets answer observation-time questions, not listing business-validity questions; schema/docs/labels make that boundary explicit.

## Security Master admission

* Ruling: use a separate source worktree because H is an openbq-docker checkout without the donor source/object, while b4b7f4b belongs to openbb-docker. Native worktree creation is attached to the articles repository and has no repository selector; use Git fallback at the already selected platform worktree root. Preserve H/C/P and donor checkout. Cost: an additional source branch/artifact to track and review.

* Task2 Ruling: use full reviewed-package dependencies with a retained primary capture per assertion; package.normalized source rows do not offer complete per-field provenance. This prevents claiming an earlier observation than any selected dependency; cost is coarse dependency invalidation until field-level mapping is qualified.

* Final: Ruling: runtime HTTP/restart was set aside by reviewer while running — subsequent native before/after evidence proves the private staging scope — cost if wrong is incorrect private readiness, not production authorization.

* Final: Ruling: production cutover/backup-restore/TemporalDB bridge remain separate incomplete release gates — this source/admission change does not claim them — cost is additional qualification before v11 release.

* Final: Ruling: retained hash identity does not independently attest provider identity authority — preserve source qualifications and conflicts — cost is unresolved authority requiring later review.

* Final: Ruling: preserve unmarked legacy-store compatibility; only marked admission roots require this protocol — avoids breaking existing local/S3 stores — cost is no retroactive admission enforcement on legacy roots.

## Retained references

* Ruling: retain lookup observations using existing Fact/assertion/publication authority, with observation-time internal effective semantics and separate nullable business bounds — existing accepted publication/pin/audit graph already provides exact source linkage — cost: this is a lookup-observation dataset, not a verified listing-history dataset. Public columns expose observed_at; effective_on/business-date filters are refused; known_at/local_received selects earlier accepted answers.

* Ruling: reuse exact existing source vectors instead of adding a new manifest wire extension — keeps authorization, capture hashes, normalizer versions, source receipt JSON and replay dependencies under existing authority — cost: current_input_vector must explicitly distinguish accepted reference observations from price Gold and remain version-aligned.

* Ruling: source lookup identity includes authority/model/full parameter tree/source context. A single lookup observation preserves multiple source rows as JSON and clears its scalar candidate when empty/multiple — avoids arbitrary candidate selection and stale current identity rows — cost: it is not a flat all-security history table; use reviewed source/model-specific extractors for broader datasets.

* Ruling: live acceptance helper uses freshlyinspected privatebridgeIP endpoints under explicitinternalHTTPtrust — NAS internalnetwork retained configuredHostPort but NetworkSettings.Ports empty; hostcurl18090failed, internalready200 and hostcurlbridge200 — no daemon/networkpolicy loosened. Cost: this does not qualify the externalgateway/browser/loopbackpublication path. First90secondhelper failurepreserved; livecollectionrerun pending. Actualruntimewashealthy; do not increase readinesswait to disguise unavailableports.

## Retained calendars

* Ruling: reuse/vend only exact Apache source validation/canonical modules and bound wrappers in P — independent TemporalDB package must not depend on OpenBB/provider runtime — cost: origin hashes and strict conformance must detect protocol drift.

* Ruling: nativecalendar source must be freshly built amd64; actual0820 image is arm64 despite earlier shorthand — source evidence remains valid for protocol/fixtures, never nativeNAS proof — cost: an additional pinned native source artifact is required.

* Ruling: current-year full bundle remains subject to MCP's existing256KiB serialized result budget; do not raise it or skip rows for wider asks — annual sample measured120701bytes for bare source row before receipt metadata, while larger spans may explicitly refuse — cost: larger workflows need narrower or authorized artifact/summary paths.

* Ruling: nativecalendar source PYTHONTZPATH empty can force pinnedtzdata: actualqualifiedarm64sourcecalendar.tz is zoneinfo.ZoneInfo, notpytz — recordbackendexplicitly ratherthanassumingpackagelabelselectsit — cost: nativebundleconformance muststillverifyservedUTCsegments.

* Ruling: a source-inspected paginationgap belongs inTask3 consumerwork: Cclient.start defaults1000 butMCPmax100rows/page; one-row nativechecks maskedthis. Newclient-ownedexecutions shoulddefault100 whileexplicitlargerHTTPpagesandoldretainedexecutionskeepsemantics — cost: morepagesforlargeHTTP-onlyqueries; exposeactualpage_sizeinretainedmetadata andverify>1000rows. P039alreadyuses100foracquisitionexecutions.

* Ruling: exactP03d3fe3 nativeartifactbuild can run afteritsownsourcefreeze whileTask3C-onlyconsumerworkcontinues — builddepends onTask2,installedqualificationstillwaitsforTask3/4 — cost: anylaterPfixinvalidatesthatcandidate andrequiresanotherbuild. Parchive9a8d15e6d22836973da03003d2bc33d41e0d5bf7377b421ac79c4d2fa30d2c07.

* Task3 Ruling: P session resolver must match existing C operational/planning refusal for incomplete source coverage and unselected candidate branches — test first returned open, then passed after explicit refusal; 28 pure tests passed. P0e14559 records correction; native03d candidate is superseded and must not be selected. Cost: incomplete bundles remain retainable but cannot establish operational sessions.

* Task4 Ruling: combine final calendar cross-store snapshot/restart/restore/replay with frozen price/SIP artifacts, as explicitly specified in the bounded price slice — avoids selecting a calendar-only restore as the whole-release gate. KeepTask4incomplete and retain3protectedcalendaroriginals while continuing independent price preparation. Cost: later price/SIP blockers also delay calendar Task4 completion; source/capture/client9/MCP3 remain only qualified checkpoints.

## Bounded prices

* Task2 Ruling: livepaidacquisition requires an outbound route absent from the isolated internal network — explicit no-key/no-HTTP TLSprobe first failed DNSgaierror(-3). Add owned provider-egress network to workeronly, leavingAPI/PG/S3/defaultinternal topology and allports/securityoptions unchanged; postchange fixed eodhd.com certificate/TLSv1.3 handshake passed withoutkey orHTTP. Authorized provider reads require this connectivity; no new arbitrary provider-origin support. Cost: worker now has general network egress atnetworklayer; application fixed-origin allowlist remains enforcement.

* Task2 Ruling: retain failedv1run d5ea90c7 (ACQUISITION_RETRY_LIMIT withmax_retries0), its1budgetreservation and0captures; no historyreset. Provision v2 with sameone-symbol/day/request/no-retry bounds and smaller32KiBbytecap; globalhourlybudget2 covers priorfailednetworkattempt+1explicitretry. Stalev1mustrefusebeforeIO. Cost: 2reservedattempts rather than pretending1total; finalproof must distinguish attempts fromacceptedproviderresponses. No automatic retry or policywindow expansion.

## SIP and final review

* Ruling: bounded SIP integration is an explicit inspection/quality-comparison Gold view, with originals and260unmatched diagnostics preserved; canonical D4tick/session eligibility staysfalse — actual source lacks original publication/enterpriseidentity evidence and currentresponse differs. Cost: this does not qualify canonicallegacy tickanalytics; finalreview must grade parentTask5 scope and leave itopen if strongerclaimsrequired.

* Ruling: the actively queried SIP exception remains exactDataset-only; a qualified inspection may also be archived as incidental snapshot closure for a declared query that excludes SIP sources. Reason: immutable shared snapshots include earlier unrelated captures, so otherwise one inspection would disable all later ordinaryprice/calendar/SQL audits. All incidental bytes/profile proofs remain validated; unknownlegacy and SQLaliases that actually includeSIP still refuse, canonicalD4 unchanged. Cost: this relies on the existing declared-source SQL enforcement; finalreview must verify no implicitSIP access through unrelated sources. Added explicit incidence/SQLalias/refusal tests plus fast runtime-union verification RED before fixing. NativeHTTP409cause confirmed by15captureclosure; no duplicateaudit created.

* Ruling: opaque signed cursor bytes may renew without changing a frozen page; client now storesboundedSHA256pagecontent fingerprints (includingorder/signedzero) plus existingreceipt/schema/count/terminal checks, then updates the next storedcapability only aftersame-page validation. Reason: nativeAPI signs expirywithcurrenttime, so rawcursor equality brokePrevious. Cost: cursorrotation safety relies on existing serverauthorization plus page/receiptintegrity; cryptographicdigest failure refusesadmission. No fullpagehistorycache or cursor-decoding authority added. REDrenewal+unchangedcursor/mutatedpage tests observed; focused39pass beforeadditionalasync/signedzeroedgechecks. Cchangesuncommitted, fulltests/build/nativebrowserrerunpending.

* Final: Ruling: retain bounded SIP inspection and exclude canonical session reconciliation/full-archive inventory certification — observed evidence is insufficient for those claims and parentMilestoneG permits bounded coverage — cost: wholearchive size/completeness/order/duplicates and canonicalmigration remain open operational followups.

* Final: Ruling: hashes prove retained-byte integrity, not independent provider/collector authenticity — operator-controlled source provenance remains explicit — cost: external attestation is not supplied.

* Final: Ruling: current-observed security bootstrap remains whole-package admission rather than historical membership or full field-level provenance — missing business/publication evidence cannot be inferred — cost: earlier historical identity requests refuse or remain unknown.

* Final: Ruling: liveYahoo/arbitraryproviders/SQLsourceinference/otherpricebases remain unqualified — recorded explicit-source tests do not establish those expanded workflows — cost: narrower supported sourcing.

* Final: Ruling: provider_operations records attached/shared provider work, not every hiddenSDK HTTP attempt — this is the observable authority boundary — cost: operational counts cannot be treated as complete external HTTP billing evidence.

* Final: Ruling: publicTLS/OAuthissuer/signedapp/publication/cutover remain separate release actions — private local auth and native staging evidence do not qualify them — cost: candidate is not a published production release.

* Final: Ruling: do not migrate/vacuum/delete MinIO or change NAS OS/capacity/unrelated services — bounded retained integration requires none of those — cost: original archive administration remains followup work.

* Final: Ruling: v11.5 analytics remains outside v11 plumbing — current evidence qualifies retained inputs and executions, not portfolio-model appropriateness — cost: analytics episodes follow separately.

* Final: Ruling: verified wheel/bundle reuse over qualified native bases is the artifact claim — clean dependency rebuild failed inode exhaustion and dependency/native source bytes were checked before reuse — cost: no clean-build reproducibility-equivalence claim.

* Final: Ruling: independent source review and private native artifact/network qualification are distinct evidence — reviewer did not inspect private bytes/attachments or rerun all historical suites — cost: operator qualification is not represented as independent reproduction.

* Final: Ruling: immutable1052test baseline plus final affected gates is the backend regression claim — 145groups completed with0failures/0errors/3skips, installedmodules separatelyqualified and genuineS3mount unavailable — cost: no finalcommit fullhistoricalsuite/genuinemount claim.

* Final: Ruling: shared043nine-example recovery is superseded only after044ten-example recovery passes — original receipts/runtime digests remain frozen — cost: no transfer of an older runtime's recovery result to new artifacts without checking.

* Final: Ruling: freshness coverage capture may differ from value-deduplicated Gold row lineage — exact retained rawbodySHA equality and actualOHLC were independently verified for this case — cost: callers must distinguish freshness from changed economic values; unequal bodies would not qualify.

* Final: Ruling: the Rita harness newline assertion is a test defect, not missing model content — original actualanswer/history already includes decision/fullpolicyID/revision2 and is revalidated without rerun — cost: firstfalsefailure remains recorded, no secondmodelcall/paidIO.

## Deferred minors

* Earlier Security Master review: standalone bundle-proof inventory completeness remains a follow-up. Native admission verifies all 22 required relations and fails closed. The final whole-release review raised no Minor findings.

## Current outcome

The final qualification report records the current artifact, interface, recovery and production-selection state. The original isolated branches and rollback targets remain available.
