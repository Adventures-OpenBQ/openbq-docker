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
- [ ] Rebuild the gateway and staged web candidate, configure a real-user demo
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
