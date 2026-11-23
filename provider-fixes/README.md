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
2.0.1 baseline is SHA guarded like provider sources. Four focused regressions
cover uppercase ISO rates, mixed-case aliases and existing snake-case styling;
the complete source suite contains171 tests including the TMX checks below. The ECB singleton-record
response is a separate frontend compatibility question, not a reason to
change its SDK return contract. Upstream candidate: OpenBQ/OpenBB platform-api.

The same V3 browser audit found two advanced-chart defaults that lacked TMX
UDF asset prefixes: futures `CGB` must be `/CGB`, and forex `USDCAD` must be
`$USDCAD`. Only widget defaults change; the regular SDK examples and query
conventions remain intact. Two regressions verify that the actual declared
defaults classify as futures/forex rather than stock. These two guarded router
files bring the overlay to110 sources and the full source suite to171 tests.

A follow-up regression keeps mixed-case option fields hidden/formatted through
normalized styling keys while their serialized wire names remain exact.

### HTTPS sidecar EIA browsers

Browser-facing EIA endpoints, nested proxy resources and RSS article links use
origin-relative paths from the actual request. This keeps a TLS-terminating
sidecar from embedding the API's internal HTTP URL, without broadening proxy
header trust. Direct SDK rendering without request context keeps its existing
configured-host fallback. Saved-view/Home URL parsing now supplies the browser
origin explicitly. Home navigation assigns its destination immediately rather
than leaving about:blank while a hidden widget waits for a paint callback.
Six network-free regressions cover HTTPS proxy paths,
mount prefixes, URL-only request info, RSS links and the direct SDK fallback.
These three EIA sources plus the ECB schema correction below bring the final
overlay to115 files and the source suite to178 tests. Live nested application
qualification remains a separate gate.

### ECB reference-rate schema aliases

The real ECB model generates lowercase serialization aliases in its JSON
schema, while the SDK's default serialization and the actual endpoint retain
uppercase ISO field names. Preserving schema keys alone cannot correct this
additional mismatch. The guarded ECB model supplies widget field overrides
from its declared model field names through json_schema_extra. The singleton
record, numeric values, parsing aliases and SDK interface remain unchanged.
A real-model schema/columns/serialized-record regression covers this contract;
the actual served catalogue and sidecar browser reference-rate check are
qualified independently.

The retired International overview/world destination is replaced with EIA's
current official international/data/ CSV portal. The description explicitly
reflects downloadable data rather than promising the removed interactive app.

The RSS bridge reloads only when feed/theme actually change, preventing a
connect→same-parameters→reload loop. Four JavaScript protocol regressions run
with `node --test scripts/test-eia-rss-protocol.mjs`; they are separate from
the178 Python source tests.

### Bounded Congress member voting history

The current117-file overlay bounds the optional complete-career vote index wait
to15seconds. A cold or unavailable index no longer hides an otherwise valid bio.
Unknown totals remain null with an explicit unavailable state in both the page
and published profile markdown; completed zero-vote and complete-career results
retain their existing behavior. The underlying full-career ingestion is unchanged; tally publication also verifies
that every required Congress/chamber is indexed. Partial totals and automatic
retry loops are not introduced.

The current suite contains183 Python regressions. JavaScript coverage adds four
member-voting UI/markdown regressions alongside the four RSS protocol tests.

## Cold FFIEC five-period reports

The sectioned Call Report keeps its five most recent reporting periods. Two
independent download workers fetch and parse older bulk archives, with a thread-local
browser session so concurrent workers cannot share cookies or view state.
Custom peer-group setup and rendering retain the same session within their thread. Only the selected bank's parsed facts are retained by completed jobs.
The Federal Reserve provider has a bounded 150-second command deadline, like
CFTC; `OPENBQ_COMMAND_TIMEOUT_FEDERAL_RESERVE` overrides it. The former 55-second
default could expire during the first two cold downloads. A warm-cache pass does
not qualify this path. Archive-wide `all_periods=true` can still be much larger
and is not the default reader verification case.

Regression coverage checks the two-download bound, the unchanged five-period
output, session isolation and explicit deadline override. The complete provider
suite now includes 187 tests; source guards cover 118 runtime files.

## Covered-call expiry filtering

The exchange form takes month numbers 1-12. The documented `YYYY-MM` API input
is normalized to that month, then returned contracts are filtered to the
requested year and month. Legacy month-only callers retain all matching years;
invalid input names `expiration` in its validation error. Unfiltered requests
retain their previous payload and results. The suite now has191 regressions
and119 guarded runtime files. Publisher-confirmed empty screens remain empty
and are not called data passes.

## Complete public-provider follow-up

The final bundle includes the canonical Dallas PDF, Federal Reserve DDP public
request profile and Nasdaq vendor/PDF/batch-error repairs qualified on V3. It
previously contained 124 guarded provider overlays and 206 provider tests. The current security and acquisition carry below expands this to129 guarded overlays. V4 retains its
calendar/routes extensions, dependency locks, and table/pivot service. The SDK
recipe also carries the established pip 26.2.0 pin and offline YFinance news
transport check from V3; this does not change the shared extension sources.

## Current security and acquisition carry

### Browser and document contracts



Platform API columns retain exact wire fields and formatting. ECB reference records keep their uppercase fields and singleton response. TMX UDF defaults use `/CGB` and `$USDCAD`. EIA links follow the browser's HTTPS sidecar origin; Home navigation is immediate and unchanged RSS parameters do not cause reload loops.

TMX chart history retains real closing prices when the source omits optional OHLC fields or supplies a range that contradicts its open/close. Those responses omit the optional OHLC set; consistent source candles remain unchanged.

Nasdaq filing downloads use HTTPS on `app.quotemedia.com`, reject URL credentials/nonstandard ports and refuse redirects. Congress bill/amendment viewers enforce their exact Congress.gov/GovInfo document origins while preserving PDF/text, empty and mixed selections. BLS and Federal Reserve raw document handlers offload blocking downloads from the API loop. The repaired PDF paths reject failed HTTP responses, HTML and incomplete PDF bodies before advertising a file. Transport header/EOF checks do not replace parsing a real file during release qualification.

Deribit quote batches preserve the first source failure when every quote fails and retain usable quotes in mixed batches. Minneapolis publications accept the exact official research repository reached by the publisher's redirect. CFTC swap defaults select a report with priceable, validated transactions within the existing ten-report bound; explicit dates remain explicit, and limits count usable transactions.

Required query parameters, provider credentials and release acceptance requirements are distinct. The catalogue has no mandatory-widget flag. Empty data and provider denials are recorded separately from successful data.

## Congress and cold FFIEC reports

The optional complete-career Congress vote-index wait is bounded to15seconds. An unavailable index does not hide a valid biography. Unknown totals remain null with an explicit unavailable state in the page/profile markdown; complete zero-vote results remain zero. Publication of complete totals verifies that every required Congress/chamber is indexed.

The sectioned FFIEC Call Report retains its five most recent reporting periods. Two independent workers download and parse older bulk archives with thread-local browser sessions. Custom peer-group setup/rendering keep the same session within their thread; completed jobs retain only the selected bank's facts. Raw NIC file downloads also retain per-thread warmed sessions.

Federal Reserve and CFTC commands have bounded150-second defaults; `OPENBQ_COMMAND_TIMEOUT_FEDERAL_RESERVE` overrides the Federal Reserve budget. A warm-cache result does not qualify the first-use report path. `all_periods=true` can request much more data and is not the default reader case. Offloading a blocking request keeps the API loop responsive but cannot force-stop that request before its existing network timeout.

## Covered-call expiry filtering

The exchange form takes month numbers1–12. `YYYY-MM` is normalized to the month, then returned contracts are filtered by the requested year/month. Legacy month-only calls retain all matching years. Invalid input names `expiration`; unfiltered calls keep their existing payload and results.

## Regression evidence

Offline tests run against installed locked providers with current sources mounted read-only. Cboe's upstream cache suite additionally uses pytest outside the production image. JavaScript RSS and member-voting protocol tests remain separate. An offline pass is not a live provider, reader installation, registered-key or native-render pass.

Qualify the final image with fresh containers and state through its Tailscale HTTPS sidecar. Keep public/demo and registered credentials in separate passes, attempt the ten chosen public/demo checks for each version, and verify actual values and usable files. Record an exhausted public EIA quota explicitly; the accepted quota exception requires the matching registered-key checks to return data. Shared HTTP transport changes require new public/demo and separate registered qualification; earlier results stay scoped to their original revisions.

Remove an overlay only when the pinned published package demonstrably contains its correction and the affected acceptance checks pass.

V4 retains its own pinned Video Library, EconDB and Yahoo Finance extension sources, BDOBB example dashboards, calendar/fiscal-year routes, managed-table service and provider-key panel. The shared provider corrections do not replace those version-specific sources.
