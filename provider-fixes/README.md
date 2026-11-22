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


### Current provider and embedded-browser compatibility

Eight guarded sources bring this release to115 provider overlays. Platform-api
columns retain exact fields and normalized formatting; the ECB reference model
explicitly describes uppercase SDK record fields without changing its singleton
response. TMX UDF defaults use /CGB and $USDCAD. EIA nested browsers and RSS links
follow the HTTPS browser origin through sidecars, Home navigates immediately,
and repeated unchanged RSS parameters do not cause a reload loop. International
uses EIA's current official CSV portal after retirement of the legacy browser.

The complete Python suite contains178 tests. Four additional JavaScript RSS
protocol regressions run with `node --test scripts/test-eia-rss-protocol.mjs`.
Reader/demo, registered, actual data, empty and source-denial outcomes remain
separate in the published regression evidence. These repairs require fresh
source/image binding and targeted live retests before release sign-off.

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

The final V1 bundle includes canonical Dallas working-paper PDF links, a consistent
public request profile for the Federal Reserve DDP endpoints, and the Nasdaq
request, PDF and batch-error repairs already qualified on later lines. PDF
downloads reject failed HTTP responses, HTML error pages and truncated documents.
Quote, company-profile and fund requests preserve the source error when all
symbols fail while retaining successful symbols in a mixed batch. Vendor error
3004 is reported as an upstream failure rather than as empty data.

This bundle contains 126 hash-checked overlays. Its installed-provider regression
suite has 231 tests; image qualification records report the observed results and
architectures. Earlier full reader and registered-key results remain separately
scoped to their source revisions. The current shared HTTP transport repairs
require new public/demo and separate registered-key qualification before release.

The Nasdaq filing downloader accepts only HTTPS links on app.quotemedia.com,
without URL credentials or nonstandard ports. Redirects are refused before
following another destination. Tests verify that private and lookalike URLs
never reach the request transport and that a public HTTPS PDF still works.

Congress bill and amendment viewers validate exact HTTPS document hosts,
URL credentials and ports before transport, refuse redirects, and reject HTTP
errors and incomplete or non-PDF bodies for PDF selections. Text files remain
text, and an invalid selection does not hide valid files in the same batch.
