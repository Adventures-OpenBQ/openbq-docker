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
the 294 Python source tests.

### Bounded Congress member voting history

The current 129-file overlay bounds the optional complete-career vote index wait
to15seconds. A cold or unavailable index no longer hides an otherwise valid bio.
Unknown totals remain null with an explicit unavailable state in both the page
and published profile markdown; completed zero-vote and complete-career results
retain their existing behavior. The underlying full-career ingestion is unchanged; tally publication also verifies
that every required Congress/chamber is indexed. Partial totals and automatic
retry loops are not introduced.

The current suite contains 294 Python regressions. JavaScript coverage adds four
member-voting UI/markdown regressions alongside the four RSS protocol tests.

A command now gets a deadline on its provider's loop: `OPENBQ_COMMAND_TIMEOUT_<PROVIDER>` if set, else the provider's built-in deadline (150 seconds for Federal Reserve and CFTC; the D8 lane kills a call 15 s later), else `OPENBQ_COMMAND_TIMEOUT`, else 55 seconds; a value that is not a positive number stops the server at startup. The overlay also raises openbb-core's `amake_request` default from 10 to 45 seconds for a whole request: fetchers rarely pass `request_timeout`, and USDA's 18.8 MB ERS feed-grains file takes 12 s on its own; a fetcher's explicit timeout still wins. For the serialized providers (CBOE, CFTC), time spent waiting for the provider's lock counts against the deadline. Past it the command is cancelled at its next await, which frees the provider's lock, and the request gets a 504 instead of hanging. `openbb_core/api/exception_handlers.py` read `error.errors` without calling it, so a provider input missing from the request returned 500 instead of 422; only a field missing from a `QueryParams` subclass (any name, e.g. openbq-yfinance's `BalanceQuery`) is a 422, so a provider `Data` model failing on an upstream response that dropped a key stays a 500. It also maps `TimeoutError` to 504 and a body that is not valid JSON to 502, each with a clear message; `openbb_core/api/app_loader.py` registers those two exceptions by type so their responses pass through the CORS middleware, which the catch-all `Exception` handler is outside of. `openbb_core/app/provider_interface.py` keeps a provider-only required input optional on the shared route but marks that provider's widget input `optional: false` (query parameters only, not `Data` fields), so the client asks for it instead of sending null.
`openbb_federal_reserve/federal_reserve_router.py` and `openbb_federal_reserve/ffiec.py` read the file viewers' `url` selection as `params.get("url") or []`, as the BLS routers do: upstream iterated `params.get("url", [])`, so a `{"url": null}` body from any of the 17 Fed multi-file viewers raised a TypeError (500) instead of returning `[]`. `openbb_government_us/usda/models/weather_bulletin_download.py` does the same for the USDA Weather & Crop Bulletin viewer: the route passes the whole body as `urls`, and upstream's validator failed on `{"urls": null}` and on a body without `urls` (500); both now return `[]`.
`openbb_sec/models/institutions_search.py` asks for a name when the search query is blank (400) and its widget marks `query` required; upstream passed `None` to `str.contains` (500), and returning every filer would be about 1.06 million rows. `openbb_federal_reserve/models/regional/dallas_bcs.py` and `dallas_igrea.py` pick the workbook sheet by its old name, then its new name (`BCS_Index_Results`, `Kilian Index`), then the only sheet, because the Dallas Fed renamed the sheets; the column layouts are unchanged. `openbb_government_us/usda/utils/ers_vegetables_and_pulses.py` and `ers_livestock_and_meat_domestic_data.py` read the renamed zip members (`vegetables-pulses-data.csv`, `Meat-Supply-Disappearance.csv`, `Meat-Statistics.csv`) case-insensitively and fall back to the old names; the CSV columns are unchanged. `ers_farm_household_income_and_characteristics.py` reads preliminary years such as `2025P` and sorts them like forecast `F` years.
Upstream-format fixes. `openbb_fred/models/tips_yields.py` drops `5` from the `maturity` choices, because FRED publishes no live 5-year TIPS (every 5-year series in release 72 is discontinued) and `maturity=5` raised a `KeyError` from `melt` (500); it is now a 422 (OpenBQ PR [7757](https://github.com/openbq-org/OpenBB/pull/7757), as revised in review). A date range with no observations still raises that `KeyError`. `openbb_famafrench/utils/constants.py` maps Australia to `Austrlia.Dat`, the name inside Ken French's country zips. `openbb_cboe/utils/helpers.py` coerces non-numeric settlement prices to null; the options file prints `CAB` for cabinet trades. `openbb_nasdaq/models/calendar_splits.py` makes numerator and denominator optional, because Nasdaq lists percentage stock dividends (`5%`) whose ratio has no `a : b` form; the row keeps its published `ratio_display`. `openbb_federal_reserve/models/list_of_banks_peer_group.py` rounds fractional thousands to whole dollars for its integer fields. The Kansas City Fed Ag credit survey, interest rates and finance databook keep their document ids but now carry quarter-versioned file names, so they resolve the current URL from the index page with `resolve_kc_ag_url`, as the district surveys already do, inside the cache producer.
`openbb_us_eia/eia_router.py` gives 25 EIA dataset widgets a `limit` of 5000 and a hidden `sort` of `desc`, so they open on the newest API page. Unfiltered, those datasets match more rows than the 500,000-row pagination ceiling and the request is refused; the REST defaults (full pagination, ascending) are unchanged. `openbb_tmx/routers/equity.py` and `openbb_tmx/tmx_router.py` drop the TMX screener builder from `widgets.json` and the TMX app, because it needs `pywry` (the `builder` extra), which the image does not install.
`openbb_tmx/utils/documents.py` lets the TMX file viewers (`filings_view`, `document_view`) read only https URLs on the hosts TMX serves those documents from: `app.quotemedia.com` for filings and `spindices.com`, `us.spindices.com` and `www.spglobal.com` for index documents. Upstream fetched any URL the request named, including services on the internal network; any other URL is now a 400 before a request is made, as the SEC fetchers already refuse hosts other than sec.gov.

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
suite includes 191 tests; source guards cover 119 runtime files.

## NY Fed catalogue units and query validation

The Federal Reserve provider serves a static `assets/regional/ny_widgets.json` catalogue in preference to generated column definitions. Apply the same correction there and in the router metadata; testing only the router does not qualify `/widgets.json`. Both copies are covered by the pristine-package hash guard and the rate-unit regression tests.

Validation errors from QueryParams subclasses with short names such as BalanceQuery are also client-input errors when their locations are present in the query. They return 422 with query locations, including rejected balance-sheet TTM requests; provider Data validation errors retain 500. The named-query value and enum regressions live in test_core.py.

## Covered-call expiry filtering

The exchange form takes month numbers 1-12. The documented `YYYY-MM` API input
is normalized to that month, then returned contracts are filtered to the
requested year and month. Legacy month-only callers retain all matching years;
invalid input names `expiration` in its validation error. Unfiltered requests
retain their previous payload and results. The suite has 191 regressions
and 119 guarded runtime files. Publisher-confirmed empty screens remain empty
and are not called data passes.

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

V6 retains its own pinned Video Library, EconDB and Yahoo Finance extension sources, BDOBB example dashboards, calendar/fiscal-year routes, managed-table service and provider-key panel. The shared provider corrections do not replace those version-specific sources.

V6 retains the `federal_reserve_` tool prefix in FFIEC and New York static MCP widget metadata so its in-process MCP catalogue matches the widget tool IDs.
