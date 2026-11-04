# Calendar baseline qualification and Security Master integration

Security Master is a required part of the v11 foundation, per the user's
November 3 direction. It is not replaced by the schedule library qualified here.

## What was exercised

The immutable provider-host image
`sha256:0820fc939831d47d87551d798b9bd42fea5d187fb5866012b91e116b5ab999f0`
contains openbq-calendar 0.1.0, openbq-routes 4.0.0, exchange_calendars 4.13.2,
pydantic 2.13.5 and tzdata 2026.5. Its installed calendar/route source bytes
matched this checkout. The installed route harness passed 13 offline checks:
capabilities, XNYS closure/early close/winter/summer, XHKG breaks, invalid and
unavailable requests, resource bounds, clipped coverage, missing-day refusal
and semantic-vs-exact-byte identity.

This is an installed-package FastAPI harness, not a deployed OpenBB registry,
gateway, authentication or NAS qualification. Networking was disabled and no
provider/account data was acquired. The report's `observed_at` records this
qualification; a bundle's `generatedAt` is separate and is not past local receipt
or provider publication evidence.

Evidence: [manifest](qualification-2026-11-03/calendar-source/manifest.json),
[report](qualification-2026-11-03/calendar-source/report.json), and exact response
bytes under `qualification-2026-11-03/calendar-source/responses/`.

```sh
python v11/calendar_source_qualification.py --verify v11/qualification-2026-11-03/calendar-source
# Use a NEW output directory for every observation:
python v11/calendar_source_qualification.py --image sha256:0820fc939831d47d87551d798b9bd42fea5d187fb5866012b91e116b5ab999f0 --output /tmp/calendar-observation-new
```

The offline verifier checks local integrity, not authenticity, signing, source
authority or database/storage durability. Prior evidence is never overwritten.

## Important findings

- The source advertises 71 calendars, with per-calendar bounds. This is a library
  catalogue, not 71 independently exchange-certified schedules.
- A closed-only ask can return a whole-year bundle. The closed date remains
  explicitly closed. Consumers must check the bundle's own coverage, not infer
  its shape from request bounds.
- A Shanghai ask starting 1990-01-01 returns HTTP 200 with coverage beginning
  1990-12-03. Earlier dates are **uncovered**, not closed. Analysis must refuse
  resolution outside that coverage even though the served portion is complete.
- Semantic `digest` excludes `generatedAt`; the exact response SHA-256 does not.
  Retention needs both identities. The synthetic correction check is only a
  controlled mutation, not a real observed correction.
- Current installed tzdata is 2026.5; older conformance bundles carry 2026.2.
  Keep complete source metadata and content digests, not only a definition label.
  The tzdata package label alone does not prove which timezone backend was active;
  retaining the image/runtime identity remains necessary.
- These files are qualification evidence. They are **not** accepted TemporalDB
  captures/publications or execution input manifests.

## Security Master source reconciliation

The original host repository at `c3223c3e9c1a4c2b26471655b35fe467f4ae0177`
contains tracked `security-master-api` 0.2.0 and `openbb-security-master` 11.4.0.
The package version does not by itself select our public release scope. The
original source was inspected read-only; those components have not yet been
copied, installed or deployed into the isolated v11 assembly.

The service owns a Delta-backed temporal identity/reference store, a guarded ODP
model API and source dependency receipts. Its current model registry includes
ReferenceResolve, ReferenceSecurity, EquityInfo/Search/Historical and
MarketCalendar. ReferenceResolve identifies listing/instrument/security;
ReferenceSecurity supplies issuer and predecessor/successor security links.
MarketCalendar carries session/trade dates, closures, breaks, interruptions,
authority and source/effective/known evidence. Field-level classification
coverage still needs qualification; do not claim every desired classification
history is already supplied.

Two concrete integration changes must precede installation:

1. The extension declares `openbb-core>=1.5.8,<2`, while the qualified v11 image
   has OpenBB core 2.0.1. Qualify/update the adapter in isolation; do not bypass
   dependency checks or downgrade the existing host.
2. Both the extension and current openbq-routes register the `calendar` entry
   point. Keep one owner of that namespace. The initial Security Master adapter
   should add `reference` routes while the existing calendar v1 bundle route
   remains available; reconcile its legacy calendar adapter explicitly.

The two calendar suppliers also differ: Security Master's inspected baseline
adapter uses pandas_market_calendars; the installed v11 bundle source uses
exchange_calendars. They must not silently substitute for or merge with one
another. Source/authority selection is a recorded policy.

## Required architecture and next building order

1. **Qualify Security Master as a service:** freeze the tracked source inputs,
   reconcile dependencies and namespace ownership, run its identity/context/
   receipt and adapter tests against synthetic data in a separate fixture store.
   Preserve the original worktrees and existing runtime pins.
2. **Define the read-only bridge:** server-authenticated ReferenceResolve,
   ReferenceSecurity and MarketCalendar under explicit contexts; ambiguous
   identity refuses instead of selecting the first ticker match. Audit scope and
   entitlement semantics rather than treating one shared Basic login as workspace
   isolation. Leave provider acquisition disabled until the existing saved-policy
   workflow can authorize it.
3. **Retain source answers in TemporalDB:** exact bounded response bytes, source
   receipt, request, local received/accepted times and normalization version.
   Preserve the source's Delta dependency versions and temporal context alongside
   local provenance. Delta versions are not TemporalDB catalog pins. Current
   source answers cannot fabricate past local knowledge.
4. **Bind reference inputs to analysis:** use a versioned input/receipt contract
   extension for the exact identity and calendar inputs. Do not attach ad hoc
   fields to strict existing wire contracts. Keeping a returned body reproduces
   that answer; rerunning arbitrary source queries also needs source version/code
   retention guarantees.
5. **Align consumers:** charts, studies, anchors, portfolio preparation and Rita
   use the same selected dated reference inputs. Keep display timezone separate.
   Only then qualify the full installed workflow and publish examples.

Security Master owns dated domain identity/reference facts. TemporalDB owns the
accepted local inputs and analysis execution receipts. Avoid building a competing
identifier database or declaring two inconsistent sources authoritative.


## Validation of this increment

- 219 existing calendar-core and route tests passed against packages installed
  in a disposable derivative of the pinned provider-host image; tests mounted
  read-only and networking disabled.
- 17 client contract/parity/provider/consumer tests passed.
- 5 local evidence-integrity tests passed, including tamper, path, symlink and
  overwrite checks; the retained final evidence verified successfully.
- Final report includes all nine request records/statuses/observation times,
  exact response references and the qualification program SHA-256.
- Independent final review found no actionable issues; final evidence replaced
  the uncommitted presentation copy while prior local observations were retained.

## Native retained-calendar checkpoint

The [native summary](qualification-2026-11-03/calendar-native/summary.json)
records exact source/image/runtime identities. A new bounded authenticated
calendar service was built for linux/amd64 from H b398d95. Startup and live
checks verified the actual pinned tzdata backend; the earlier arm64 harness
is retained as separate evidence.

The isolated TemporalDB42 candidate explicitly collected real XNYS2026,
XHKG2026 and clipped XSHG1990 bundles, retained their byte hashes and waited
for each capture's accepted Silver publication. Exact/current/local-known-at
queries passed for all three. The production client provider verified all nine
native result pages through its shared cache/calendar seam. Authenticated MCP
returned matching original/new results and provenance; anonymous and scope
spoofing attempts were401, and an acquisition write remained denied.

The calendars preserve library-baseline evidence, not exchange certification.
The closed NYSE holiday and early close, Hong Kong's separate segments and
Shanghai's uncovered earlier dates remain distinct. Calendar Gold and historical
provider-publication claims are absent. The three original results are protected
by audit runs. Final frozen restart/restore/replay will cover the calendar,
price and bounded SIP examples together; this checkpoint leaves that release
gate open. Actual visible widgets and live Rita also remain separate gates.
