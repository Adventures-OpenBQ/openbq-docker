<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbb-eodhd in ODP v9

`source/` is the openbb-eodhd provider extension (9.6.3), ported from
bdobb-dev/openbb-docker v9.6.3 with its openbb-eodhd fixes through v9.6.6
(`source.json`; per-file record in [docs/v9/eodhd-port.md](../../docs/v9/eodhd-port.md)).
Its own README describes the data. `Dockerfile.v3` builds it as a wheel and
installs it on the locked ODP recipe with the provider-fixes overlay applied.

## Where it is served

This line installs no standard routers (no openbb-equity, openbb-etf and so
on), so `provider="eodhd"` has no `obb.equity...` home here. The extension's
own namespace carries it: 52 commands under `/api/v1/eodhd/` (`obb.eodhd.*`),
one per standard model EODHD implements, each offering only `eodhd`. Their
widgets are `eodhd_<path>_eodhd_obb`, category EODHD; for example
`eodhd_equity_price_historical_eodhd_obb` is `/api/v1/eodhd/equity/price/historical`.

`source/openbb_eodhd/assets/apps.json` holds one app, `EODHD` (Company,
Ownership and Markets tabs, eight cards). The extension serves it on
`/api/v1/eodhd/apps.json` and openbb-api merges it into `/apps.json`, as it
does the other provider apps. It does not go in `examples/bdobb/apps.json`.

## Key

`EODHD_API_KEY` in `credentials.env` (empty in `credentials.env.example`).
Without it EODHD requests are refused with a client error; the rest of the API
is unaffected. Data access depends on your EODHD plan.

## Tests

- `source/tests`: the extension's own unit tests (mocked SDK). The parity tests
  in `test_eodhd_router.py` compare the mirrors with the standard routes, so
  run them where the standard routers are installed, as the donor's CI does.
- `tests/test_stack.py`: this line's checks, without standard routers: the 52
  mirrors, their widgets, the EODHD app on `/apps.json`, a price query through
  `/api/v1/eodhd` against saved bars (`tests/fixtures`, fictional values), a
  missing key, and the app under `OPENBB_API_AUTH=true`.
- `verify.py` runs `tests/` at image build time, after checking package
  versions and the EODHD SDK pin.

None of these call EODHD. `source/scripts/smoke.py` is a live check against
EODHD's public `demo` token; it uses the standard routes, so it needs them.

## SDK

The official EODHD library is built from the commit `source/pyproject.toml`
pins (GitHub archive `f98e69d`). Its dependencies resolve with the ODP lock as
constraints, so no locked version moves; the packages it adds are not yet
recorded in a lock file. Record them (`pip freeze` against
`requirements.lock`) at the first image build and switch the install to
`--no-deps` with that lock, as `v3/yfinance` does.
