# Bounded real daily-price policy qualification

Continue the approved v11 reference/NAS roadmap natively. This slice proves one
real paid-provider miss→accepted execution→policy-cache-hit workflow. It does not
expand the Security Master's unknown historical business intervals.

## Evidence and bounded assertion

Use Block NYSE Class A, provider symbol XYZ.US, only January 21, 2025. The
half-open installed operational map is [2025-01-21,2025-01-22). Do not map SQ,
ASX or other dates, and do not call this historical S&P 500 membership.

The January 9 issuer announcement states the NYSE SQ→XYZ transition starts
January21 and the CUSIP remains unchanged; ASX January22 is separate. The
retained EODHD rename-history row independently agrees. Current EODHD General
reports XYZ, NYSE, USD and CIK0001512673. The admitted Security Master returns
its owned issuer/listing/security IDs for XYZ. Current General and Security
Master do not provide CUSIP/ISIN here: the security ID is a provisional provider
symbol identity. Preserve that limitation. The one-day mapping is an explicit,
source-based operator assertion, not certified lifetime identity history.

Retain exact source bodies privately with byte hashes and local receipt clocks;
commit only their evidence manifest and declared limitations. Validate hashes,
rename venue/date/symbol, issuer CIK and the admitted IDs before producing the
existing strict five-field IdentityMap entry. The entry digest must equal the
installed normalizer/projection identity recorded in the run. The source evidence
manifest binds that digest to its rationale; source-generation, local receipt
and historical business clocks remain separate. No fake validity dates enter
Security Master. No automatic expansion from ticker, IPO date or index join date.

## Run and authorization

Install only the owned qualification stack's bounded map and explicit EODHD
source/account configuration. Keep provider secrets out of Git, receipts, URLs
in diagnostics and MCP/UI. Freeze an account-scoped saved policy revision:
1 identity,1 day,1 concurrent call, small byte/request budget and bounded timeout.
Use an explicit restricted acquisition credential; existing read-only MCP identity
must remain unable to acquire. Discovery/preflight do no provider work.

Prove a cache miss, submit the exact reviewed policy revision with an idempotency
key, wait for this run's accepted normalization/Gold/execution, and compare
original provider bytes/rows. Repeat under the same policy and prove a hit with
no extra provider request. Test out-of-window and stale-policy rejection before
IO. Preserve adjustments, source clocks, identity basis and missing-data limits
in the run/evidence. This is a real single-equity example, not portfolio coverage.

Resolve the date against a separately retained XNYS2025 bundle. A valid session
is not proof of price coverage. Signed-price support stays intact. No new
acquisition request schema, implicit provider grants or synthetic market prices.

## Shared release gate

Calendar native source/capture/client/MCP qualification can precede this slice,
but the final consistent snapshot/restart/restore/replay should cover the frozen
calendar, price and bounded SIP examples together. Until that succeeds, calendar
Task4 and parent release gates remain open. Actual visible widget/Rita and the
>1000-row complete-result checks also remain required. No main/push/cutover.
