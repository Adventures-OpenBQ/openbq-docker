# Independent review of the v9 Docker CORS fix

Reviewed Docker `2c546467..2d6cc1c2c76675762968f38187a5da1ca66b47ba` for existing PR #33 and the paired client product commit `776c82f8`. The supplied patch matches the Git diff with ten lines of context.

## Strengths

- The pinned launcher’s console script resolves to `openbb_platform_api.main:main`. Its `app/app.py:92` loads Core’s default app and `:104` then calls the bootstrap helper. Core registers CORS at `provider-fixes/openbb_core/api/rest_api.py:81`. Bootstrap returns early for an existing CORS registration at `provider-fixes/openbb_platform_api/app/bootstrap.py:45`; it also serves custom apps through `:190`. Each registration now exposes exactly `Link`, `Content-Range` and `Access-Control-Expose-Headers`. This covers both initialization paths and preserves a custom app’s own policy.
- I compared both copies against locally cached 2.0.1 distribution sources. Removing the four attribution lines and the one new middleware argument from each reconstructs the pristine SHA-256 in the manifest. Both distribution metadata files identify Apache-2.0. The root license, the two new NOTICE entries and the modified-file headers follow the repository’s existing treatment. Both package pins agree with `requirements.lock:79` and `:93`. The installer checks all package versions and pristine files before its first copy at `provider-fixes/apply.py:18`.
- The exact source comparison covers origin, method, request-header, credentials and authentication behavior. The two captured authorization preflights also agree on every policy field. The installed custom-app test verifies the explicit origin, credential permission and sole custom exposure after bootstrap. The seven changed paths contain no provider, receipt, SDK or proxy changes. The paired client release record documents the image requirement and the refusal on the preview-prefixed route at `docs/releases/validation/v9/live-observed-returns/acquisition-backport.md:75` and `:79`.
- The raw baseline log records two missing-exposure failures and a passing custom-policy control. The patched logs record 57 overlay tests, 3 installed CORS tests, 12 workspace tests, 121 CI-equivalent tests and 15 subtests passing. The local arm64 image descriptor matches the build log’s index `sha256:c80732d2037ef55855c99f05b85d5ac5ef6e47427588b51f09af0a9bbfb826cb`. Its configured command is `openbb-api`.
- In the eight real Fetch observations, Chromium and WebKit each refused both old-image responses, admitted the patched equity response with 28 returns per listing, and refused the patched ETF response with its visible next-page Link. Each case retained 58 rows, unknown completeness and the installed widget’s `results` selector. The raw baseline ETF headers independently show the Link hidden from browser JavaScript. The probe used the installed launcher app and a recorded SDK fixture. Browser observations (`task-1-evidence/fix1/docker-installed-browser.log`, retained local evidence) · Probe (`task-1-evidence/fix1/installed-image-browser.mjs`, retained local evidence) · Fixture (`task-1-evidence/fix1/installed-image-fixture.py`, retained local evidence)

## Issues

Critical, important and minor findings are all empty. No corrective change is requested.

## Declined to judge and evidence limits

- Fresh provider entitlement or upstream data quality is outside this transport correction. The image probe supplied a test credential and replayed the recorded SDK data.
- The browser-to-image fault injected a next-page Link. The HTTP 200 Content-Range check on bootstrap has installed ASGI coverage at `provider-fixes/tests/test_cors_exposure.py:31`. The broader client transport cases have their own review.
- Installed-image evidence covers the local Linux arm64 artifact. I inspected the build, installed and browser logs without repeating passing suites. Deployment, additional architectures and PR integration are outside this review.

## Verdict

**Specification approved. Code quality approved. Ready to push `2d6cc1c` to the existing unmerged v9 Docker PR #33.** The two one-argument middleware edits supply the paired browser contract at both registration points, with version and source guards and direct evidence for the positive and refusal paths.
