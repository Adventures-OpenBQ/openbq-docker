# TemporalDB browser principal boundary

The approved Vercel activation sequence requires a verified GitHub user to
resolve to a separately configured TemporalDB scope. Inspection found that
the table relay already carries this identity, but the temporal relay still
uses one shared desktop credential. Public TemporalDB activation stays off
until that boundary is repaired.

The web server must require its distinct table relay credential when TemporalDB
is enabled and send the authenticated session's `github:<numeric-id>` assertion
with that credential. Browser-supplied assertions must never be forwarded.
The gateway verifies those headers with its existing relay validator and picks
a backend token from a bounded server-only `TEMPORALDB_PRINCIPAL_TOKENS` JSON
object. Missing, malformed, duplicate, unknown or forged assertions fail closed
before contacting the backend. A web request never falls back to the desktop
token. Existing desktop requests without relay assertions retain their current
credential. All configured credentials remain distinct.

No upstream scope protocol, receipt ownership, retained result identity or
database migration changes. The managed table ingestion configuration must
bind the same principal to the same backend scope. The production demo needs
an explicitly prepared scope and data; qualification receipts are not rewritten.

## Implementation plan

Use native execution in the existing isolated client and host worktrees.

- [x] Add failing HTTP tests for two users, unknown/forged/duplicate assertions,
  missing assertions, and unchanged desktop behavior; validate malformed and
  reused map credentials.
- [x] Add the bounded gateway configuration and per-request credential choice.
- [x] Add failing web tests proving session-derived assertions replace browser
  values, require the private relay setting, and never appear in bootstrap.
- [x] Implement web relay changes and update enabled-feature fixtures.
- [x] Run complete gateway and web suites, inspect the cross-service contract,
  and record review evidence before merging or deploying.
- [x] Rebuild the gateway and staged web candidate, configure a real-user demo
  scope and matching managed ingestion binding, then qualify privately.
- [ ] Activate only the authenticated public gateway and promote with rollback
  after the real browser acceptance checks are ready.

Review focus: no fallback after failed assertions; no inherited mapping keys;
no credential reuse across users; duplicate raw headers; no secrets in errors,
bootstrap, versioned configuration or logs.

## Verification and review

The initial gateway regression demonstrated that both users received the
desktop credential. The initial web regressions demonstrated acceptance of a
missing relay setting and absence of the session assertion. Each failed for
the intended reason before its fix. Complete suites then passed: **196 gateway
tests and 94 web tests**.

An independent reviewer found one qualification-harness regression: its gateway
had no web mapping. The harness now fails closed unless a distinct scoped
`webApiToken` is supplied, redacts it and maps its synthetic GitHub 42 session
explicitly. A private HTTP integration probe through the actual web and gateway
servers verified two distinct backend credentials, replacement of forged
browser headers, 403 for an unmapped allowed user and 401 for a disallowed
session, with no backend calls for either refusal. The reviewer independently
reran that probe and reported no remaining critical or important findings.

These checks use synthetic authentication fixtures and a local HTTP upstream;
they do not claim real OAuth, market-data, public TLS or retained-data browser
acceptance. Existing live credentials, scope policy and ingress are unchanged.

## Integration checkpoint

Merged client source: `3c0fa4d1c7c681a2bcd03782cc2d67099fb4c096`.
Merged gateway source: `835dcc4`.
The NAS candidate image is
`sha256:557da9000025301afbf291b129380d1c1556cb0718e364ac26fca74879f208c2`.
It extends the retained qualified gateway image with only the reviewed
`config.mjs` and `server.mjs`; it is not described as a clean dependency rebuild.
All nine TemporalDB gateway tests passed inside that candidate image on the NAS.
The live gateway was unchanged at that build checkpoint; activation is recorded below.

The main push completed a successful staged Vercel build:
[DaiBwwkPYQz3c8W4t425GqaLV2PA](https://vercel.com/bdobb-dev/openbq-bdobb/DaiBwwkPYQz3c8W4t425GqaLV2PA).
The full client CI is also running; its completion must be checked separately
from the already passed affected suites. Production domains remain on the
previous deployment with manual promotion required.

A private activation bundle was prepared outside Git. It retains the original
configuration hashes and adds one new real-user demo workspace, one distinct
scoped credential and matching gateway/managed-ingestion bindings. Both the
actual API scope-policy parser and gateway configuration parser accepted it.
It grants no provider acquisition permission, seeds no data and changes no
existing scope or receipt. It is **not applied**. Private deployed acceptance,
intentional demo-data admission, Vercel relay configuration and public ingress
remain deployment gates, not completed work.

## Private NAS activation and acceptance

The scoped configuration and gateway candidate image were subsequently applied.
The API was recreated with its existing image, stores and network aliases; the
gateway was recreated with the reviewed image. Managed ingestion reads its
private binding configuration per acquisition, so the table service needed no
restart. No database migration, provider acquisition permission or public
ingress was introduced.

Actual private HTTP and HTTPS acceptance passed:

* The real GitHub principal resolves to its own empty demo workspace.
* Forged and unmapped assertions are refused. Another scope's saved query is
  inaccessible. All 20 original desktop saved queries remain available.
* Managed-table acquisition of the same retained input succeeds for its original
  desktop owner with the same execution and result hash, and is refused for the
  new demo principal. Temporary test table sources and sessions were disposed;
  no Temporal query execution was created by this check.
* HTTPS checks verified the certificate chain and expected hostname. The probe
  pinned the transport to the address reported by Tailscale because MagicDNS
  resolution was unavailable in the probe container; TLS verification stayed on.
* The v11 and legacy API readiness endpoints pass. TCP ports and HTTPS handlers
  match the previous configuration. All Funnel flags are false or absent;
  the runtime omits redundant false entries for the three new ports.

Rollback was actually rehearsed: all four original configuration files were
restored byte-for-byte and the original gateway image restarted. The reviewed
configuration was then reapplied and the private, HTTPS and managed-data
acceptance checks passed again. The guarded rollback script is retained at:

```text
/share/Container/openbq-v11-staging/cutovers/20261104-web-principal/rollback.sh
```

This rolls back configuration and gateway image without deleting retained data.
It refuses unrelated configuration changes. The original whole-v11 entry-point
rollback remains available separately.

The newest client main is `573fb1bfc1e0fbb74d24d22f4ecc98849f5556ef`
following PR #40. Its Vercel build succeeded at
[Dzs6zapUMe1DssEVSgA9GgnxMbQ9](https://vercel.com/bdobb-dev/openbq-bdobb/Dzs6zapUMe1DssEVSgA9GgnxMbQ9).
Its replacement [full CI run](https://github.com/Adventures-OpenBQ/bdobb/actions/runs/41851055344)
passed all five jobs, including browser E2E (313 passed, 11 skipped). The earlier
`3c0fa4d1` run was cancelled by the subsequent main push. These CI results do
not establish real OAuth acceptance of the public deployment.

The real demo workspace now has a durable Bronze capture: nine actual AAPL
daily bars for January 2–12, 2024, fetched through the qualified Yahoo adapter
and received November 4, 2026 (New York). This was an explicit operator bootstrap,
not an automatic saved-policy acquisition. The receipt uses local-received
knowledge time; it does not claim the data was known in 2024. Silver acceptance
and a retained-result widget remain unverified because a preceding FRED capture
held the catalog lock. The user scope still has no acquisition permission.
Private Vercel credential import, public gateway activation and real OAuth/browser
acceptance remain outstanding. Production domain promotion remains manual.


## November 5 real-data qualification

A separate, explicit operator acquisition retained one actual EODHD AAPL.US daily
bar for November 3, 2026 in the real user's scope. This uses the admitted Apple
listing and issuer IDs already present in the live map, within the current
Security Master observation window. No historical membership or January 2024
identity coverage is inferred. No identity configuration was changed for this
check; the original Yahoo January capture remains Bronze only.

The EODHD sample reached accepted Bronze, Silver and Gold. A saved query returned
one complete row, pinned to hot snapshot 23 and the archived execution runtime
`ab5a40f74e23ce86a7eff7ff11f153b30af8bd098490b39bfb74876f06a5a772`.
Its result hash is
`2a3707682c5ad756c804d6310fe12b638784fe17a839ef4a0372fbac71af7655`.
The managed table applied a raw view, reported an exact count of one and exported
one final batch. The original temporal execution ID, hash, snapshot and receipt
survived ingestion and export. Decimal prices remained exact strings. Adjusted
close remained null with `unavailable_dependencies`; missing corporate-action
inputs were not silently supplied.

The desktop credential could not read this user-owned saved query, and all 20
original desktop queries remained available. Temporary verification sources,
sessions and exports were disposed; the saved query, execution and source
capture remain. This was a bounded operator bootstrap, with automatic user
acquisition permission still off. Two earlier operator probes failed before
retention (binary-envelope JSON serialization, then a read-only archive write);
they are recorded privately and excluded from successful-capture claims.

This qualifies the private HTTP service path, not real OAuth browser interaction
or public Vercel ingress. API, worker, gateway and table image IDs still matched
the selected November 4 images when checked. NordVPN remained connected while
the isolated localhost-only userspace Tailscale proxy supplied NAS SSH access.
