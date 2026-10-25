<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# OpenBQ reference backend v3 implementation plan

Goal: package the OpenBQ-maintained reference backend and the existing Episode 3
pivot examples as one private, testable v3 example service.

Approved design: use a pinned OpenBQ revision, retain the reference recipe fixes,
and add the pivot examples alongside its widgets. The primary ODP service stays
separate. Its market providers still supply the optional market examples.

Source: openbq-org/backends-for-openbb, commit
`a6293707576e16edda8305adda95b07b6a4b968b`, directory
`getting-started/reference-backend`.

- [ ] Assemble the pinned reference source, extend CORS through the existing
  environment variable, remove the Python execution widget and include its license.
- [ ] Add the fictional pivot widgets, app catalog, embedded logo and health route
  to the real reference FastAPI app. Avoid replacing the reference data routes.
- [ ] Test actual registry resolution: reference + fictional cards resolve on this
  service; market cards are explicitly attributed to ODP, never fake-resolved.
- [ ] Test representative table, PDF, form and WebSocket routes, removed execution
  route, logo, CORS and duplicate-registration guard.
- [ ] Pin the resolved Python dependency environment and package the combined
  service into the existing private v3 Compose overlay on HTTPS 8443.
- [ ] Verify container build/run where available; record any external blocker.
  Update the series companions and privacy checks without tagging a release.

Rulings: work in the existing relaunch checkouts to preserve the ongoing changes.
Do not rewrite historical tags. The v3 client currently uses file import; do not
claim an Apps browser. Dedicated Statement view is not in this checkpoint.
