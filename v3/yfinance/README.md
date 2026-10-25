<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Original OpenBQ yfinance extension in ODP v3

The `Dockerfile` stage `v3` installs the source pinned in `source.json` as an Apache-2.0
wheel on the existing locked ODP recipe. No legacy `openbb-yfinance` adapter
is installed. The source's original LICENSE and NOTICE travel with the wheel.

Only five missing SDK packages are added, at recorded versions. Existing ODP
package versions stay unchanged; `pip check` and the V5 discovery/query gate
must pass during the image build. The SDK is yfinance 1.7.0 and the extension is
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
