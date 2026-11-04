# Bounded calendar source

Build from an exact source archive containing `calendar-core/openbq_calendar`,
`v4/routes/openbq_routes/calendar_v1.py` and this directory. Record the source
commit, archive SHA-256, recipe SHA-256 and immutable native image ID. This
recipe copies the source-controlled Apache calendar package and route; it does
not install the entire provider host or use an arbitrary upstream.

Runtime requires private `CALENDAR_SOURCE_USER` and `CALENDAR_SOURCE_PASSWORD`
(at least 32 printable ASCII characters). Supply these in an operator-owned
read-only environment file, never command output or committed configuration.
Run as UID/GID 65532, read-only root, bounded memory/CPU, dropped capabilities,
no-new-privileges and a bounded `/tmp` tmpfs, on the owned qualification network.
Only port 6906 inside that network is required. Do not publish it publicly.

`PYTHONTZPATH` is deliberately empty. Startup refuses a system ZoneInfo path
or a package profile different from exchange_calendars 4.13.2, tzdata 2026.5
and pydantic 2.13.5. The hash-locked requirements file pins all dependencies.
The source uses library baseline rules, not exchange-certified evidence.

Authenticated GET endpoints are `/api/v1/calendar/trading/v1/calendars` and
`/api/v1/calendar/trading/v1/bundle`. Bundle asks require one canonical calendar
ID and inclusive ISO start/end, at most 366 days. The existing route may return
whole-year coverage; a response over 1 MiB is refused. `/health` reveals only
process readiness. Mutation, docs and arbitrary source endpoints are absent.

A healthy source is not retained acceptance. Explicit capture must retain exact
bytes, obtain the capture's accepted normalization receipt, and bind the public
execution to that publication. Check incomplete coverage as unavailable,
semantic and byte digests separately, and the execution's actual runtime and
input vector. NAS installed/replay qualification is tracked separately.
