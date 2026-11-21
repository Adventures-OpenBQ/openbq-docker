# Paired v9 API CORS overlay

Docker baseline `2c546467` on `codex/v9-live-observed-returns`, paired client fix `776c82f8992faac6b7e125144ea42cb0593d4395`. The previous local qualification image was `openbq-v9-live-observed-returns:review-75a9026-2c54646-20261120` with OCI identity `sha256:f8cca8ee400a88f4ae331bc498c9e28520e9ff766410926bbfdac0e4edd29404`.

## Actual launcher and overlay

The stock 2.0.1 platform launcher imports the default app from `openbb_core.api.rest_api`. Core installs CORS before the launcher calls `apply_cors_from_system_service`. That helper sees Core's middleware and returns early. The baseline actual launcher gave HTTP 200 with `Access-Control-Allow-Origin: *` and no exposure list. Therefore updating only the bootstrap helper would leave the default image unchanged.

Both existing middleware registrations now pass the exact list `Link`, `Content-Range`, `Access-Control-Expose-Headers`. Compared with the original installed files, the copies add this single argument and the existing Apache attribution header. The current provider hashes, credentials settings, supplied CORS origins/methods/request headers, and custom-app middleware deduplication retain their original handling. The API overlay checks both locked packages and both pristine hashes before copying any files.

| Pinned source | Pristine SHA-256 |
| --- | --- |
| `openbb_core/api/rest_api.py` in OpenBB Core 2.0.1 | `1d15258594fb30e516c90de10b27f0adad92ad126391c9fb0cf4a85e993cd5cc` |
| `openbb_platform_api/app/bootstrap.py` in OpenBB Platform API 2.0.1 | `279de218b7de81da6b1d073010ea5a0b73621645aad5971babcfbb3f12294e5b` |

The existing `provider-fixes/apply.py` enforces versions and hashes before all existing overlay copies. `NOTICE` and the overlay README identify both upstream sources. No dependency, vendor, provider receipt, or proxy prefix changes are part of the Docker fix.

## Installed baseline RED

Run from the Docker worktree.

~~~sh
docker run --rm --network none --entrypoint python \
  -v "$PWD/provider-fixes/tests/test_cors_exposure.py:/tmp/test_cors_exposure.py:ro" -w /tmp \
  openbq-v9-live-observed-returns:review-75a9026-2c54646-20261120 \
  -m unittest -v test_cors_exposure
~~~

Exit 1, two intended failures and one pass. The real Core app's HTTP 200 and the fresh FastAPI app registered through the actual launcher bootstrap both omitted exactly the three exposure names. The custom CORS control retained its explicit origin, credentials mode and custom exposure. Both failures occurred before writing the overlay.

## Overlay and repository gates

~~~sh
scripts/test-provider-fixes.sh
python3 scripts/check-public.py --history HEAD
python3 -m unittest discover -s workspace/tests
uv run --isolated --no-project --python 3.12 --with pytest --with starlette==1.7.0 \
  --with httpx==0.28.1 --with anyio==4.15.1 --with pyyaml \
  python -m pytest v3/tests tests -q -p no:cacheprovider
~~~

All four commands exited zero. The pristine `odp` overlay applied 43 files and ran 57 passing tests, including the two new exposure cases and the custom-policy control. Public-content and reachable-history scanning passed. Workspace assembly passed 12. The Python CI-equivalent suites passed 121 tests and 15 subtests. The latter produced a Starlette deprecation notice for the existing TestClient HTTPX dependency. Host `python3` lacked pytest, so the test used isolated Python 3.12 and the CI dependencies.

## Actual browser-to-image comparison

The ignored SDK fixture (`task-1-evidence/fix1/installed-image-fixture.py`, retained local evidence) runs the installed default OpenBB API under Uvicorn. It replaces only the SDK call with the checked-in recorded 58-row public response, validates the expected SDK request parameters, and adds an explicit next-page Link to the ETF response as a test fault. The default API's existing middleware, both genuine generated widget routes and their receipt producers run from the image. Only loopback ports are published.

The Playwright probe (`task-1-evidence/fix1/installed-image-browser.mjs`, retained local evidence) runs real Chromium and WebKit against the app's Vite browser origin. It uses native cross-origin Fetch to observe transport headers and runs the application's actual widget discovery, fetch, table builder and recipe entry against the same image. The browser path uses no Playwright interception or fulfillment. The client release matrix separately covers both actual executor/worker modes and the Parameters UI. The direct browser-to-image comparison uses recorded SDK data, not new entitled provider traffic.

The first fixture setup omitted the SDK context-manager protocol and returned HTTP 500. The recorded SDK stub was corrected and the owned baseline container relaunched. One shell diagnostic used a reserved zsh variable and one restart collided with the original container's asynchronous cleanup. A distinct test container name and a bounded readiness wait resolved both. The continued baseline returned HTTP 200 and 58 rows with valid receipt envelopes from both mirrors before browser qualification. Its raw ETF response had a next-page Link. Chromium and WebKit hid that Link and the missing exposure policy and the client refused live authority while keeping all 58 rows on both routes.

## Fresh v3 image

~~~sh
docker build --target v3 -t openbq-v9-live-observed-returns:cors-qualification-20261121 .
~~~

Exit zero. The existing build gates passed, including 25 installed EODHD tests, 11 EconDB tests, the videos link check, yfinance and the installed calendar/fiscal routes. Expected warnings in the negative provider fixtures appeared in the build logs.

| Local `linux/arm64` image identity | Digest |
| --- | --- |
| OCI index | `sha256:c80732d2037ef55855c99f05b85d5ac5ef6e47427588b51f09af0a9bbfb826cb` |
| Platform manifest | `sha256:0405235d193b68edf84e27369c6552033cf668d739e4a65ced87bb8b43c21fc5` |
| Config | `sha256:2829bb14563942765222fae61a586d6fb9f545791f809754de53de22f1114ffd` |

### Installed verification

~~~sh
docker run --rm --network none --entrypoint sh -w /tmp \
  -v "$PWD/provider-fixes/tests/test_cors_exposure.py:/tmp/test_cors_exposure.py:ro" \
  -v "$PWD/scripts/verify-requests-trust-bundle.py:/tmp/verify-requests-trust-bundle.py:ro" \
  openbq-v9-live-observed-returns:cors-qualification-20261121 \
  -c 'python -m pip check && python /tmp/verify-requests-trust-bundle.py && python -m unittest -v test_cors_exposure'
~~~

Exit zero. `pip check`, the Requests trust-bundle gate and all three targeted installed CORS tests passed. The trust gate used certifi 2026.10.23 and bundle SHA-256 `2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b`. Existing provider-import resource/deprecation warnings appeared in the installed unit log.

The cross-origin browser comparison runs from the client worktree. The two containers use the same fixture and capture mounts. One uses the previous qualification tag and one uses the patched tag. Docker supplies temporary loopback ports.

~~~sh
evidence=.superpowers/sdd/2026-11-21-v9-acquisition-backport-publication/task-1-evidence/fix1
capture=e2e/fixtures/installed-observed-returns/75a9026/public-demo.json
PIVOT_WASM_VERIFY_ONLY=1 pnpm exec vite --mode browser --host 127.0.0.1 --port 19585 --strictPort
# In a separate terminal, start each image with its own container name.
docker run --rm -d --name "$test_container" -p 127.0.0.1::6900 --entrypoint python \
  -v "$PWD/$evidence/installed-image-fixture.py:/run/price-fixture.py:ro" \
  -v "$PWD/$capture:/run/price-fixture.json:ro" "$image_tag" /run/price-fixture.py
# Set each API to the loopback address reported by docker port for its container.
BDOBB_PRICE_APP=http://127.0.0.1:19585 BDOBB_PRICE_BASELINE="$baseline_api" BDOBB_PRICE_PATCHED="$patched_api" \
  pnpm exec node "$evidence/installed-image-browser.mjs"
~~~

Exit zero. Chromium 151.0.7922.34 and WebKit 26.5 each observed all four image and route combinations.

| Image and route | Browser-observed response | Recipe result |
| --- | --- | --- |
| Baseline equity mirror | 200, exposure list unavailable | Refused. |
| Baseline ETF mirror | 200, exposure list and injected Link unavailable | Refused. |
| Patched equity mirror | 200, full three-name exposure policy | Qualified box with 28 observed returns per listing. |
| Patched ETF mirror | 200, full exposure policy and visible next-page Link | Refused. |

Each case kept 58 rows, unknown table completeness, and the installed `results` selector. An actual authorization OPTIONS preflight against each image returned 200 with identical allowed origin, methods, authorization header and cache age. Both images omitted Allow-Credentials in that default response. The explicit custom-credentials test remains in the installed suite.

The OCI tag stays local for independent review. The test containers and loopback browser server were stopped. The EODHD source tree and receipt logic have no changes in this Docker diff.

## Review handoff

Docker commit `2d6cc1c2c76675762968f38187a5da1ca66b47ba` is clean. Review `2c546467..2d6cc1c` alongside the [client qualification](https://github.com/Adventures-OpenBQ/bdobb/blob/60cbc4f89944fc3864d708834ca7573bcedf98dd/docs/releases/validation/v9/live-observed-returns/acquisition-backport.md). The pre-commit public-content scan and post-commit diff check passed. Raw gate logs and browser evidence (`task-1-evidence/fix1/`, retained local evidence)

## Independent review closeout

A fresh independent reviewer approved source commit `2d6cc1c2c76675762968f38187a5da1ca66b47ba` without blocking or minor findings. [Full independent review](acquisition-transport-review.md). This local arm64 image uses recorded SDK responses; it is not a new entitled provider fetch or a deployed release. Raw probes and logs remain with the client task evidence. All existing PRs stay open and unmerged.
