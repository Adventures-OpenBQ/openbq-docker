<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Public demo keys: receipt

`credentials.demo.env` holds only demo values the providers publish for trying their APIs. Each was
checked with one small live request; only the HTTP status and the date are recorded.

| Provider | Variable | Demo value | Where it is documented | Check (one request) | Status | Date (UTC) |
|---|---|---|---|---|---|---|
| EIA (API v2) | `EIA_API_KEY` | `DEMO_KEY` | api.data.gov developer manual (DEMO_KEY: 30 requests/hour, 50/day per IP). EIA's own pages name no demo key; api.eia.gov accepts api.data.gov's. | `GET api.eia.gov/v2/steo/` | 200 | 2026-10-14 |
| Congress.gov | `CONGRESS_GOV_API_KEY` | `DEMO_KEY` | api.data.gov developer manual (same limits) | `GET api.congress.gov/v3/bill?limit=1` | 200 | 2026-10-14 |

Still keyless on 2026-10-14, so nothing for them goes in the file:

| Provider | Check | Status |
|---|---|---|
| BLS (API v2, no `registrationkey`) | `POST api.bls.gov/publicAPI/v2/timeseries/data/` (one CPI series, one year) | 200, `REQUEST_SUCCEEDED` |
| CFTC (Socrata, no app token) | `GET publicreporting.cftc.gov/resource/6dca-aqww.json?$limit=1` | 200 |
| EconDB (temporary token, as the provider asks for one) | `GET www.econdb.com/user/create_token/?reset=0` | 200 |

A key set in `credentials.env` always overrides its demo value. No provider in this stack now needs a
key it did not need before.
