<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Original OpenBQ yfinance extension in ODP v3

The `Dockerfile` stage `v3` installs the source pinned in `source.json` as an Apache-2.0
wheel on the existing locked ODP recipe. No legacy `openbb-yfinance` adapter
is installed. The source's original LICENSE and NOTICE travel with the wheel.

Only five missing SDK packages are added, at recorded versions. Existing ODP
package versions stay unchanged; `pip check` and the V5 discovery/query gate
must pass during the image build. The SDK is yfinance 1.8.0 and the extension is
openbq-yfinance 3.0.0. The recipe rebuilds the generated Python namespace.

The market app uses four confirmed auto-generated widgets:

- `yfinance_equity_historical_yfinance_obb`
- `yfinance_fundamental_income_yfinance_obb`
- `yfinance_fundamental_balance_yfinance_obb`
- `yfinance_fundamental_cash_yfinance_obb`

It also uses ODP's `sec_insider_trading_sec_obb`. These differ from the older
shared asset-class router IDs. Financial statements return long-form rows;
the generic pivot recipe groups `line_item` and splits reporting `date`.

The build gate executes actual V5 Python/REST queries with a stubbed public SDK
boundary. This establishes integration and null handling, not live Yahoo access.
No provider API key is required by our yfinance extension.

The SDK is pinned to1.8.0 because Yahoo retired the `/xhr/ncp` company-news
feed. The upstream GraphQL replacement (yfinance commit
`9a4cf3fbb435032a65e13480defc0b75f0e6229e`) ships in1.8.0. The root lock also
pins its required `curl_cffi==0.17.0` and `certifi==2026.10.19`. The image build
runs an offline request-contract regression for news, all, and press-release
tabs; live news qualification is separate.
