<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# EconDB provider (openbb-econdb)

No PyPI `openbb-econdb` supports openbb-core 2: the last release, 1.5.1, requires `openbb-core<2`, and
OpenBB Platform 5 dropped the provider. Every PyPI release (1.1.0 and up) is also AGPL-3.0-only. So
`source/` is the provider as it stood in the OpenBB repository at `174d7e69` (2024-05-14), the last
commit under the MIT License, ported to openbb-core 2.0.1 (`source.json`, `source/NOTICE`). The port
is small: no `nest_asyncio`, pandas 3 fixes, a router, and a hatchling `pyproject.toml`.

openbb-core 2 serves each provider under its own namespace, so the routes are
`/api/v1/econdb/economy/indicators`, `/available_indicators` and `/country_profile`, and the widgets:

- **`econdb_economy_indicators_econdb_obb`** (Indicators, table): `symbol` (e.g. `RGDP`, `CPI`,
  `URATE`, or `main`) and `country` (two-letter, e.g. `US`); a country-level symbol without a
  country is a 422.
- `econdb_economy_available_indicators_econdb_obb`
- `econdb_economy_country_profile_econdb_obb`

The ODP 4 id `economy_indicators_econdb_obb` came from the shared economy router, which this stack
does not install. No key: with no `ECONDB_API_KEY` the provider asks EconDB for a temporary token
(`/user/create_token/`), cached for 12 hours. Checked live on 2026-10-14: RGDP/US, CPI/US,DE, main/JP,
the indicator list (4,516) and the US profile all answered 200.

`Dockerfile` builds the wheel in its pinned builder stage and install it with `--no-deps`; its
dependencies (openbb-core, aiohttp-client-cache, aiosqlite) are already pinned in `requirements.lock`,
which is unchanged. `verify.py` runs `tests/` (unittest, EconDB's HTTP stubbed) as the build gate.
