# Provider compatibility overlay

This release keeps the published OpenBB provider versions and applies reviewed compatibility corrections at image build time. `apply.py` checks each package version and every original file hash before copying any source. New files must be absent. Any mismatch stops the build.

The overlay combines earlier release-line repairs with current upstream corrections: source moves and response shapes; provider-loop isolation and deadlines; credential-safe errors and input validation; CFTC lookback bounds; Cboe cache concurrency and option strategies; Fama–French archive/table selection; SEC taxonomy and 13F parsing; Deribit exchange-expiry dates; DataFrame/date round trips; numerical indicators; custom certificate paths; IMF port names; Treasury CSV preservation; and the reachable Benzinga RSS default feed; and FFIEC taxonomy-cache validation with authoritative report datatype recovery; and SEC adviser blank-value preservation and SIC table-header parsing; and bounded, contract-compatible TMX UDF chart history; and IMF multi-dataset REST input normalization; and anonymous BLS series access with optional registered-key support; and NY Fed core-trend ISO date parsing; and canonical EIA WPSR price workbooks with separate retail frequencies and propagated parsing errors. Delayed Cboe quote and volatility requests include the site Referer required by the current CDN while preserving caller request options. Required query parameters and provider credentials are distinct from release acceptance requirements; the catalogue has no mandatory-widget flag.

Upstream reference: [openbq-org/OpenBB](https://github.com/openbq-org/OpenBB). Additional ports reference PRs 7833, 7857, 7583, 7620, 7758, 7762, 7796, 7807, 7808, 7818, 7820, 7823, 7827, 7831, 7834, 7835, 7836, 7840, 7843, 7856 and 7859. Overlapping fixes are combined rather than replacing a file with competing snapshots. Original provider copyright and Apache-2.0 notices are retained.

Offline source regressions run against the built image with this directory mounted read-only. The Cboe upstream cache suite additionally needs pytest; that test tooling is not part of the production image. A passing offline suite is not a live provider regression, reader installation pass or registered-key acceptance.

Remove an overlay only after a pinned published package demonstrably includes its corrections and the affected acceptance tests pass.

Cboe CDN requests now carry its required public `Referer` across cached/uncached
helpers and direct historical/snapshot requests. Explicit caller headers and
timeouts are preserved. HTTP errors are rejected before response decoding, and
futures directories validate their JSON data shape. This extends the earlier
quote-only header repair; uncached live controls reproduced403without the
header and200JSONwith it on both old and new transports.

### V3 browser-audit supplement: serialized widget field names

The platform-api column generator must preserve OpenAPI property keys as the
wire field names. Converting `USD` to `usd` or `netAssetValue` to
`net_asset_value` creates columns that cannot address the actual response.
The overlay preserves normalized classification for formatting, pinning and
other styling, while keeping each column's `field` exact. Explicit author
field overrides and exclusions remain supported. The pinned platform-api
2.0.1 baseline is SHA guarded like provider sources. Three focused regressions
cover uppercase ISO rates, mixed-case aliases and existing snake-case styling;
the complete source suite now contains 168 tests. The ECB singleton-record
response is a separate frontend compatibility question, not a reason to
change its SDK return contract. Upstream candidate: OpenBQ/OpenBB platform-api.

The same V3 browser audit found two advanced-chart defaults that lacked TMX
UDF asset prefixes: futures `CGB` must be `/CGB`, and forex `USDCAD` must be
`$USDCAD`. Only widget defaults change; the regular SDK examples and query
conventions remain intact. Two regressions verify that the actual declared
defaults classify as futures/forex rather than stock. These two guarded router
files bring the overlay to110 sources and the full source suite to170 tests.
