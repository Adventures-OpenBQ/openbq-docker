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

The current 119-file overlay bounds the optional complete-career vote index wait
to15seconds. A cold or unavailable index no longer hides an otherwise valid bio.
Unknown totals remain null with an explicit unavailable state in both the page
and published profile markdown; completed zero-vote and complete-career results
retain their existing behavior. The underlying full-career ingestion is unchanged; tally publication also verifies
that every required Congress/chamber is indexed. Partial totals and automatic
retry loops are not introduced.

The current suite contains 191 Python regressions. JavaScript coverage adds four
member-voting UI/markdown regressions alongside the four RSS protocol tests.

A command now gets a deadline on its provider's loop: `OPENBQ_COMMAND_TIMEOUT_<PROVIDER>` if set, else the provider's built-in deadline (150 seconds for CFTC; the D8 lane kills a call 15 s later), else `OPENBQ_COMMAND_TIMEOUT`, else 55 seconds; a value that is not a positive number stops the server at startup. The overlay also raises openbb-core's `amake_request` default from 10 to 45 seconds for a whole request: fetchers rarely pass `request_timeout`, and USDA's 18.8 MB ERS feed-grains file takes 12 s on its own; a fetcher's explicit timeout still wins. For the serialized providers (CBOE, CFTC), time spent waiting for the provider's lock counts against the deadline. Past it the command is cancelled at its next await, which frees the provider's lock, and the request gets a 504 instead of hanging. `openbb_core/api/exception_handlers.py` read `error.errors` without calling it, so a provider input missing from the request returned 500 instead of 422; only a field missing from a `QueryParams` subclass (any name, e.g. openbq-yfinance's `BalanceQuery`) is a 422, so a provider `Data` model failing on an upstream response that dropped a key stays a 500. It also maps `TimeoutError` to 504 and a body that is not valid JSON to 502, each with a clear message; `openbb_core/api/app_loader.py` registers those two exceptions by type so their responses pass through the CORS middleware, which the catch-all `Exception` handler is outside of. `openbb_core/app/provider_interface.py` keeps a provider-only required input optional on the shared route but marks that provider's widget input `optional: false` (query parameters only, not `Data` fields), so the client asks for it instead of sending null.
`openbb_federal_reserve/federal_reserve_router.py` and `openbb_federal_reserve/ffiec.py` read the file viewers' `url` selection as `params.get("url") or []`, as the BLS routers do: upstream iterated `params.get("url", [])`, so a `{"url": null}` body from any of the 17 Fed multi-file viewers raised a TypeError (500) instead of returning `[]`. `openbb_government_us/usda/models/weather_bulletin_download.py` does the same for the USDA Weather & Crop Bulletin viewer: the route passes the whole body as `urls`, and upstream's validator failed on `{"urls": null}` and on a body without `urls` (500); both now return `[]`.
`openbb_sec/models/institutions_search.py` asks for a name when the search query is blank (400) and its widget marks `query` required; upstream passed `None` to `str.contains` (500), and returning every filer would be about 1.06 million rows. `openbb_federal_reserve/models/regional/dallas_bcs.py` and `dallas_igrea.py` pick the workbook sheet by its old name, then its new name (`BCS_Index_Results`, `Kilian Index`), then the only sheet, because the Dallas Fed renamed the sheets; the column layouts are unchanged. `openbb_government_us/usda/utils/ers_vegetables_and_pulses.py` and `ers_livestock_and_meat_domestic_data.py` read the renamed zip members (`vegetables-pulses-data.csv`, `Meat-Supply-Disappearance.csv`, `Meat-Statistics.csv`) case-insensitively and fall back to the old names; the CSV columns are unchanged. `ers_farm_household_income_and_characteristics.py` reads preliminary years such as `2025P` and sorts them like forecast `F` years.
Upstream-format fixes. `openbb_fred/models/tips_yields.py` drops `5` from the `maturity` choices, because FRED publishes no live 5-year TIPS (every 5-year series in release 72 is discontinued) and `maturity=5` raised a `KeyError` from `melt` (500); it is now a 422 (OpenBQ PR [7757](https://github.com/openbq-org/OpenBB/pull/7757), as revised in review). A date range with no observations still raises that `KeyError`. `openbb_famafrench/utils/constants.py` maps Australia to `Austrlia.Dat`, the name inside Ken French's country zips. `openbb_cboe/utils/helpers.py` coerces non-numeric settlement prices to null; the options file prints `CAB` for cabinet trades. `openbb_nasdaq/models/calendar_splits.py` makes numerator and denominator optional, because Nasdaq lists percentage stock dividends (`5%`) whose ratio has no `a : b` form; the row keeps its published `ratio_display`. `openbb_federal_reserve/models/list_of_banks_peer_group.py` rounds fractional thousands to whole dollars for its integer fields. The Kansas City Fed Ag credit survey, interest rates and finance databook keep their document ids but now carry quarter-versioned file names, so they resolve the current URL from the index page with `resolve_kc_ag_url`, as the district surveys already do, inside the cache producer.
`openbb_us_eia/eia_router.py` gives 27 EIA dataset widgets (25, plus Crude Oil Imports and Total Energy, which passed 500,000 rows by 2026-11-17) a `limit` of 5000 and a hidden `sort` of `desc`, so they open on the newest API page. Unfiltered, those datasets match more rows than the 500,000-row pagination ceiling and the request is refused; the REST defaults (full pagination, ascending) are unchanged. `openbb_tmx/routers/equity.py` and `openbb_tmx/tmx_router.py` drop the TMX screener builder from `widgets.json` and the TMX app, because it needs `pywry` (the `builder` extra), which the image does not install.
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

## Sources that moved or changed shape (2026-11-17)

Found by the v5 regression of 2026-11-17 (`release/v5` 1d69be8): 18 Atlanta Fed cases, 7 Cboe options cases and 2 Minneapolis cases answered HTTP 500, and four Congress cases answered 500 while the first bulk load was running. Each file below is the pinned upstream source with only the change described.

**Atlanta Fed data files moved, not removed.** The bank moved its downloads under `/-/media/Project/Atlanta/FRBA/Documents/research-and-data/`; the old paths redirect to `https://www.atlantafed.org/error` (404), so every Atlanta data command failed with `HTTPError -> 404 Client Error: Not Found for url: https://www.atlantafed.org/error`. The seven `URL` constants in `openbb_federal_reserve/models/regional/atlanta_*.py` now read as in upstream PR [7822](https://github.com/openbq-org/OpenBB/pull/7822) (open, not ours). Two file names changed too. All seven new URLs answered 200 on 2026-11-17. The workbook layouts are unchanged, so the parsers are untouched.

| Model (commands) | Old path under `…/FRBA/Documents` | New path |
|---|---|---|
| `atlanta_bie.py` (business_inflation_expectations) | `/research/inflationproject/bie/data/bie.xlsx` | `/research-and-data/data/business-inflation-expectations/bie-data.xlsx` |
| `atlanta_gdpnow.py` (gdpnow) | `/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx` | `/research-and-data/data/gdpnow/GDPTrackingModelDataAndForecasts.xlsx` |
| `atlanta_market_probability.py` (market_probability) | `/cenfis/market-probability-tracker/mpt_histdata.xlsx` | `/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx` |
| `atlanta_sbu.py` (business_uncertainty) | `/datafiles/research/surveys/business-uncertainty/sbu-data.xlsx` | `/research-and-data/surveys/business-uncertainty/sbu-data.xlsx` |
| `atlanta_sticky_cpi.py` (sticky_cpi) | `/datafiles/research/inflationproject/stickprice/stickyprice.xlsx` | `/research-and-data/data/sticky-price/sticky-price-data.xlsx` |
| `atlanta_taylor_rule.py` (taylor_rule, taylor_rule_measures, taylor_rule_heatmap) | `/datafiles/cqer/research/taylor-rule/taylor-rule-data.xlsx` | `/research-and-data/data/taylor-rule/taylor-rule-data.xlsx` |
| `atlanta_wage_growth.py` (wage_growth) | `/datafiles/chcs/wage-growth-tracker/wage-growth-data.xlsx` | `/research-and-data/data/wage-growth-tracker/wage-growth-data.xlsx` |

**Minneapolis business conditions.** `business_conditions_prices.csv` now heads its period column `month` (it was `Date`), which raised `KeyError: 'Date'`. `openbb_federal_reserve/models/regional/minneapolis_business_conditions.py` reads the first column of both CSVs as the period whatever it is called. Local fix, no upstream PR yet.

**Cboe options chains with a digit in the contract root.** Adjusted contracts such as `B1SPY261120C00710000` did not fit the contract-symbol pattern, left a NaN expiration and raised `TypeError: strptime() argument 1 must be str, not float` for the whole chain (SPY on 2026-11-17: 224 of 12,380 contracts). `openbb_cboe/models/options_chains.py` is the file at the head of upstream PR [7841](https://github.com/openbq-org/OpenBB/pull/7841) (`bf6879b`, open, not ours). Those contracts stay in the chain with their own root (`B1SPY`) as `underlying_symbol`.

**Dallas Fed manufacturing and service-sector surveys.** The workbooks' only sheet was renamed from `Index` to `Sheet1` (seen 2026-11-17), so both answered 422 "Worksheet named 'Index' not found". `dallas_tmos.py` and `dallas_tssos.py` pick `Index`, then `Sheet1`, then the only sheet, as `dallas_bcs.py` and `dallas_igrea.py` already do.

**FINRA equity securities.** FINRA retired its Market Data Center (`finra-markets.morningstar.com` answers 301 to the Investments Explorer page), so classifying symbols newer than the bundled asset raised "The FINRA security lookup was not readable." (400). `openbb_finra/utils/directory.py` is the file at the head of upstream PR [7805](https://github.com/openbq-org/OpenBB/pull/7805) (`19547d3`, open, not ours): the list keeps FINRA's weekly-summary universe and the bundled classifications, and newer symbols are listed without a security type. `equity/search` and `equity/profile` read the same retired service and still fail; they need a new source.

**Cboe index constituents with no file.** Cboe answers 403 for 29 of the 58 European index symbols the command accepts (the sector and style indexes, for example `BUKENGY`; checked 2026-11-17), and the Cboe Market Data app opened its constituents card on `BUKENGY`, so the card showed "Unexpected Error -> ContentTypeError -> 403" (500). `openbb_cboe/models/index_constituents.py` answers "Cboe publishes no constituents for BUKENGY." and `openbb_cboe/assets/apps.json` opens the card on `BUK100P`. The 29 symbols are still offered as choices.

**Congressionally mandated reports.** GovInfo's link service answers 500 "No static resource cmr/tableofreports" for `/link/cmr/tableOfReports` (2026-11-17; its own API docs still list the route), and the loader read that body as an empty list, so the table and its viewer were empty. `congress/utils/bulk.py` falls back to the keyless GovInfo search (`collection:CMR AND congress:N`), which the file already uses elsewhere. The search carries no submission or deadline dates, so those are blank in fallback rows and `is_on_time` is unknown; `congress/models/congress_mandated_reports.py` lets it be null. The link route is used again as soon as it answers.

**USDA livestock and meat international trade.** ERS changed the layout of all 14 workbooks (footer "Date run: 11/04/2026"): the header row starts with `Commodity description`, every data row repeats commodity, trade flow, unit, geography code and geography name in columns A to E, the year-to-date header is `Jan-Sep-25`, and the summary row is `World total`. The parser found no header and returned nothing (204) for every request. `usda/utils/ers_livestock_and_meat_international_trade_data.py` reads the new layout only. Product names are now ERS's own (`Cattle for breeding`, not `Cattle, cattle for breeding`).

**Atlanta Fed publications.** Fed in Print's recent Atlanta items carry only a DOI, no `citation_pdf_url` or `File(s)` link, so every candidate was dropped and the viewer's list was empty (204). `openbb_federal_reserve/utils/fedinprint.py` follows the DOI to the paper's page and takes the first PDF it links. The fallback applies to any district's DOI-only item.

**OECD presentation table in the OECD app.** The app opened the table (`DF_QNA_INCOME::T0107`, Australia, quarterly) with a saved `end_date` of 2020-01-01, and the request answered 400 "Empty response from OECD for dataflow 'DF_QNA'". The same request without the end date returns the table, so `openbb_oecd/apps.json` drops it. Not established: whether OECD returns nothing for any end date combined with the widget's row limit (`lastNObservations`); OECD throttled the checks.

**Congress amendment text viewer default.** The viewer opened on `119-hamdt-2`, a House amendment with no published text, so it showed "No documents for these parameters." `congress/congress_router.py` opens it on `119-samdt-2`, which has a Congressional Record page.

**FFIEC BHCPR default quarter.** The NIC lists a quarter for a holding company before its report is published (JPMorgan and Bank of America showed 2026 Q3 with `pdfAvailable` false on 2026-11-17); the CSV for it is an error page, so the default request returned no data (204), and the empty result was cached for the day. `openbb_federal_reserve/models/ffiec/bhcpr.py` leaves unpublished quarters out of the filed list, so the default is the newest published one. The period dropdown still offers the unpublished quarter.

**Cboe term structure on an expiry with one strike.** With the chain loading, SPY's 2026-12-02 expiry listed a single strike (825) above the price, so it had no out-of-the-money put, the strike lookup returned `None`, and the chart raised `TypeError: unsupported operand type(s) for -: 'float' and 'NoneType'` (500). `openbb_cboe/utils/options/create_term_structure.py` leaves that side of that expiry off the chart. The straddle on the same expiry still answers 400 "No premium data found for the selected strikes", which is the right answer for it.

**Congress bulk loader lock.** `openbb_government_us/congress/utils/bulk.py` kept one `asyncio.Lock` per cache key. A lock belongs to the event loop that first waits on it, and the Congress commands run on more than one loop (the provider's loop and the server's), so a request arriving during a load raised `RuntimeError: <asyncio.locks.Lock …> is bound to a different event loop`. The locks are now kept per (loop, key), as `_WRITE_LOCKS` in the same file already is; two loops can each run a load once, with the same result. Local fix, no upstream PR yet.

Covered by `tests/test_moved_sources.py`.

### Federal Reserve DDP public-client compatibility

The catalogue, release calendar, structure XML and SDMX downloads send a
consistent browser-compatible User-Agent and Accept profile. The current public
site rejects the default programmatic client profile: the live baseline returned
403 or timed out, while the scoped headers returned 200 with the actual release
catalogue through the same SDK transport. Each request gets a fresh header mapping
because the core helper merges caller settings into it. This adds one guarded
source (120 total). Three offline regressions exercise the catalogue, structure
and economic-row download boundaries. Live cold-container acceptance remains a
separate gate. Upstream candidate: openbq-org/OpenBB's Federal Reserve DDP client;
the current develop file still makes these requests without the explicit profile.

## Nasdaq filing PDF transport (V8 walk)

`openbb_nasdaq/utils/helpers.py` (openbb-nasdaq2.0.0, Apache-2.0) requests the selected filing with the existing PDF Accept profile, checks HTTP status and refuses HTML or incomplete PDF bodies before base64 encoding. A real AAPL8-K download previously returned a Cloudflare HTML error labelled as a PDF; the PDF request profile returned the actual document. Four transport regressions cover HTML, HTTP403, truncation and PDF-byte round-trip. Upstream `openbq-org/OpenBB` develop blob `dbd7c9f1ff99a284c0569aed9c6d211a7344578a` still has the text header and unchecked body; this scoped repair is an upstream PR candidate. The viewer still reports upstream download refusals truthfully.

## V9 daily-price acquisition CORS exposure

The pinned OpenBB Core and Platform API 2.0.1 files `openbb_core/api/rest_api.py` and `openbb_platform_api/app/bootstrap.py` expose `Link`, `Content-Range` and `Access-Control-Expose-Headers` through their existing CORS middleware. A browser can then read both daily-price continuation declarations and the exposure policy itself. The default app configures middleware in Core before the launcher runs. The bootstrap helper covers apps that use the launcher's CORS defaults and leaves existing custom middleware in place. The overlay keeps the configured origins, methods, request headers and credentials policy.

Nasdaq transport can report `rCode=200` with business error `3004` (vendor
failure). The shared helper rejects that response, including partial payloads.
Quote, company-profile and fund-info fetchers preserve the original exception
when every requested symbol fails, so the API can report a source failure
instead of an empty 204. Working symbols still return their data when another
symbol fails; ordinary empty responses retain their existing behavior. The
regressions cover integer/string business codes, partial payload refusal,
all-symbol failures and mixed successful/failed symbols.
