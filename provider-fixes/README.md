# Provider compatibility overlay

This release keeps the published OpenBB provider versions and applies compatibility corrections at image build time. `apply.py` checks every declared package version and original source hash before copying any file. New overlay paths must be absent; a mismatch stops the build. `original-sha256.json` is the complete runtime-source inventory. Qualification records report the tested source, image, dependency versions, test counts and architectures.

The bundle combines upstream fixes with local provider repairs:

- Provider moves, response shapes, source failures, required query inputs and credential-safe errors.
- Provider-loop isolation, command deadlines, TLS/custom certificates, and request-session ownership and cleanup.
- CFTC lookback bounds and priceable swap report selection; Cboe cache concurrency, option strategies and required public CDN headers; Fama–French archive/table selection; Deribit exchange expiries; numerical indicators and DataFrame/date round trips.
- SEC taxonomy, 13F, adviser blanks and SIC headers; FFIEC taxonomy-cache validation, report datatypes and cold report sessions.
- IMF names and multi-dataset inputs; Treasury CSV preservation; reachable Benzinga RSS defaults; anonymous BLS series with optional registered keys; NY Fed core-trend ISO dates.
- Canonical EIA WPSR workbooks, separate retail frequencies, propagated parsing errors, HTTPS browser/RSS links and the current international CSV portal.
- Dallas working-paper PDF locations, Federal Reserve DDP request compatibility, and explicit Nasdaq vendor/all-symbol failure handling with successful mixed results retained.

Upstream reference: [openbq-org/OpenBB](https://github.com/openbq-org/OpenBB). Additional ports reference PRs 7833, 7857, 7583, 7620, 7758, 7762, 7796, 7807, 7808, 7818, 7820, 7823, 7827, 7831, 7834, 7835, 7836, 7840, 7843, 7856 and 7859. Overlapping fixes are combined rather than replacing a file with competing snapshots. Original provider copyright and Apache-2.0 notices are retained.

## Browser and document contracts

Platform API columns retain exact wire fields and formatting. ECB reference records keep their uppercase fields and singleton response. TMX UDF defaults use `/CGB` and `$USDCAD`. EIA links follow the browser's HTTPS sidecar origin; Home navigation is immediate and unchanged RSS parameters do not cause reload loops.

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
