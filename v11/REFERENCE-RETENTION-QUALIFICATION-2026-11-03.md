# Retained reference data: installed checkpoint

TemporalDB source `c2c93de722092f94b6de2e27a5d657b34fbb441a` is installed
in the isolated NAS qualification project, with migration 41. Production is
unchanged. This checkpoint qualifies reference observations and replay, not
completion of v11.

The native linux/amd64 image is
`sha256:a729c82ff507f9ddb9412919cbd065d9a22c42f4c8af31333458e2f4f767d442`.
Its independently runnable archived environment is
`0723d0fd65e2835cc3e4bcd9ffb33133670fb940260408650d984951001b2730`.

## What passed

- Live authenticated collection from the admitted S&P 500 Security Master:
  AAPL `ReferenceSecurity`, AAPL `ReferenceResolve`, and an XNYS
  `MarketCalendar` lookup using the audited calendar identifier.
- Exact raw response bytes retained in Bronze, fenced normalization into accepted
  Silver, exact publication pins, and saved-query results served through the
  same retained-result API used by widgets. Response hashes matched throughout.
- All three executions protected as audit runs. With application writers and
  database/object-store processes stopped, the four owned volumes were archived
  and hash-checked. A separate project restored those volumes using the same
  immutable images. Original rows survived, and all three audit replays matched
  the original rows, schemas and result hashes using the archived environment.
- Installed tests: **116 passed** with networking disabled and installed runtime
  imports. Fresh source gates: **28 reference tests**, **74 integration tests**,
  generated-schema drift check and exact wheel/source verification.

The earlier frozen backend baseline separately completed **1,049 passed and
3 skipped**. Installed modules and the unavailable host mount are separate
gates; that baseline is not a full-suite claim for the later source commit.

## What the observations mean

AAPL business validity is unknown; capture time does not supply a historical
listing start. The calendar response is empty and **uncovered**, not closed.
The source refused an unmapped MIC lookup; no exchange mapping was invented.
A durable capture acknowledgement is distinct from accepted publication: the
installed check waited for its exact capture's normalization receipt.

NAS internal networking did not expose the configured host loopback ports.
Acceptance used inspected private bridge addresses. External gateway/browser
access remains unqualified by this checkpoint. Positive dated sessions, dated
price identity, the bounded SIP example and final product integration remain
separate gates. The temporary restore project is stopped with evidence and
volumes retained; the qualification project remains running.

See TemporalDB's `docs/schema/reference-lookups.md` for the Bronze/Silver/result
walkthrough and the distinction between observation time, local knowledge and
business validity. Private credentials, topology, raw receipts and backup
archives are deliberately kept outside this repository.
