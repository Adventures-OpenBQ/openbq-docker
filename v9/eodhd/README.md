<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# openbq-eodhd in ODP v9

`source/` is the openbq-eodhd provider extension 9.0.1, vendored from
Adventures-OpenBQ/openbq-eodhd at commit
`6f9f1cb20475c3204867bf03c3f3dc5f7141ca96`. That package is bdobb-dev/openbb-docker's
`openbb-eodhd` (v9.6.3, fixes through v9.6.6), renamed `openbq-eodhd` (module `openbq_eodhd`)
(`source.json`; per-file record in [docs/v9/eodhd-port.md](../../docs/v9/eodhd-port.md)),
plus the released 9.0.1 fixes, guarded earnings-versus-estimates model and
opt-in financial chart evidence.
Its own README describes the data. The `Dockerfile` builds it as a wheel and
installs it on the locked ODP recipe with the provider-fixes overlay applied.

## Where it is served

This line installs no standard routers (no openbb-equity, openbb-etf and so
on), so `provider="eodhd"` has no `obb.equity...` home here. The extension's
own namespace carries it: 53 commands under `/api/v1/eodhd/` (`obb.eodhd.*`),
one per standard model EODHD implements, each offering only `eodhd`. Their
widgets are `eodhd_<path>_eodhd_obb`, category EODHD; for example
`eodhd_equity_price_historical_eodhd_obb` is `/api/v1/eodhd/equity/price/historical`.

`source/openbq_eodhd/assets/apps.json` holds one app, `EODHD` (Company,
Ownership and Markets tabs, eight cards). The extension serves it on
`/api/v1/eodhd/apps.json` and openbb-api merges it into `/apps.json`, as it
does the other provider apps. It does not go in `examples/bdobb/apps.json`.

## Financial chart evidence

The screener, dividends and income mirrors accept `chart_source=true`.
Select rows at `results` and read the receipt from the same completed
response at `extra.results_metadata.chart_evidence`. The generated
screener widget formats the fractional five-day change as a percentage.
Dividends expose the events' payment currency and split-adjusted amount.
The income receipt reports the statement's own currency. Ordinary EODHD
responses leave dividend coverage and income scale unknown. The provider
contract defines the receipt and the explicit snapshot authority for these
facts. [Provider receipt contract](source/docs/chart-source-contracts.md)

## Key

`EODHD_API_KEY` in `credentials.env` (commented out in `credentials.env.example`).
Without it the committed `credentials.demo.env` supplies EODHD's public `demo` token, which answers
only EODHD's demo symbols (AAPL.US, TSLA.US, VTI.US, AMZN.US, MCD.US, BTC-USD.CC); other symbols
are refused with a client error, and the rest of the API is unaffected. Data access depends on your
EODHD plan. Both API images (the `Dockerfile` stages `api` and `v3`) install the extension.

## Tests

- `source/tests`: the extension's own unit tests (mocked SDK). The parity tests
  in `test_eodhd_router.py` compare the mirrors with the standard routes, so
  run them where the standard routers are installed, as the donor's CI does.
- `tests/test_stack.py`: this line's checks, without standard routers: the 53
  mirrors, their widgets, the EODHD app on `/apps.json`, a price query through
  `/api/v1/eodhd` against saved bars (`tests/fixtures`, fictional values), a
  missing key, the chart-source and legacy responses, and the app under
  `OPENBB_API_AUTH=true`.
- `tests/test_source_pin.py` checks the local source inventory and hashes
  against `source.json`.
- `verify.py` runs the runtime tests at image build time, after checking package
  versions and the EODHD SDK pin. To rerun the runtime verifier against
  the built API image, run these commands from the repository root.

```sh
docker build --target v3 -t openbq-eodhd-chart-candidate .
docker run --rm --network none -v "$PWD/v9/eodhd:/check:ro" \
  openbq-eodhd-chart-candidate python /check/verify.py
```

None of these call EODHD. `source/scripts/smoke.py` is a live check against
EODHD's public `demo` token; it uses the standard routes, so it needs them.

## SDK

The official EODHD library is vendored inside the package, at
`source/openbq_eodhd/_vendor/eodhd` (MIT, upstream commit `f98e69d`; see
`source/NOTICE`), so nothing fetches it at build time. Its runtime
dependencies (numpy, pandas, requests, rich) are all in the ODP lock, and the
images install the wheel `--no-deps`, as `v3/yfinance` does.
