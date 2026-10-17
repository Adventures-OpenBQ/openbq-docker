<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Episode 1 verification

Passed on October 5, 2026, on the x86-64 NAS. Release source is identified by tag `v1.0.0`; this is a local NAS image, not a published registry image.

- Docker `27.1.2-qnap8`; Compose `v2.29.1-qnap2`.
- Final locked image: `sha256:4b6bbfc98174821d97c3b33cd5c7eaa908f6e6cd91a3939ab6437a6bc420d96f`.
- Python base: `python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d`.
- Exact installed package inventory: `requirements.lock`; `pip check` returned no broken requirements.
- After force-recreating both containers, the API became healthy. From the Mac over private Tailscale HTTPS, smoke passed: 927 widgets, 1,148 schema paths, app/agent catalogues, and one nonempty CBOE AAPL quote result.
- HTTPS catalogue access passed and raw sidecar port 6900 was unreachable. NAS LAN and tailnet port 6900 also rejected connections; Docker reports no published API ports.
- Markers in both settings and OpenBBUserData volumes survived recreation. The dedicated Tailscale node retained its node ID, domain, and IP.

Initial API route discovery took about two minutes; the proxy can return 502 before the API is ready. Initial certificate issuance encountered a Tailscale control-plane timeout and subsequently succeeded. A temporary sidecar MTU experiment was reverted to 1500 before successful tests; it is not a required configuration or a proven fix. No NAS firewall changes were made. A subsequent HTTPS size check successfully downloaded the full widget catalogue (4,927,924 bytes) and OpenAPI schema (8,424,773 bytes).

This verifies one supported data route and this NAS architecture. Workspace/browser compatibility belongs to Episode 2. See the [series rehearsal report](https://github.com/artcashin/adventures-in-openbq-articles/blob/v1.0.0/editorial/rehearsals/v1/REPORT.md).

## Episode 6 (Rita and MCP)

Verified on October 7, 2026. Candidate images (private GHCR, recipe `Adventures-OpenBQ/agent-rita`), each built for linux/amd64 and linux/arm64:

- Rita: `ghcr.io/adventures-openbq/openbq-rita:6.0.0-candidate@sha256:ff90afeeea6c9da4e27e5d5719afaf4ab275e67b9a1c171c14698d63af0f1a99`
- MCP: `ghcr.io/adventures-openbq/openbq-mcp:6.0.0-candidate@sha256:d76fbbac7392e58c71572195f1208c1ba03d4b959260c49e07a817c69851c8d2`

Deployed on the x86-64 NAS into the running stack, merged with its existing services; only the two new services were started and no existing container was recreated. Smoke was unchanged before and after: 995 widgets, 68 yfinance widgets, and the reference backend at 71 widgets / 73 cards / 0 missing references. Rita `/status` and MCP `initialize` (10 tools) answered through private Tailscale HTTPS on 10443 and 11443, and Rita's SSE stream arrived incrementally. Rita shares the Tailscale sidecar's network namespace, so it reaches the tailnet model endpoint through MagicDNS (model list returned 200 from inside the container). A restart of both services came back through Serve. Funnel is off on every port.

Rita was rebuilt on October 10, 2026 with agent-rita patches 0010 (a non-JSON body
answers 400, not 500), 0011 (follow-up suggestions only on the final answer) and
0012 (one retry of an empty first step), recipe `sha-9c370be`:
`ghcr.io/adventures-openbq/openbq-rita:6.0.0@sha256:6e4224846448ce26b908b76edbc180ffc77ad8509564e2317126825113c4e520`. It replaced the October 7 image
on the NAS alone; `agents.json` answered 200, a malformed POST answered 400, and
the live gate passed 21 of 22 (the search, add and set case fails on the model's
conduct, as with patch 0011). MCP is unchanged.

Built from source on October 16, 2026 (the GHCR images above stay private and are no longer
used). On the x86-64 NAS, from an export of this commit and an empty Docker client config (no
registry login): agent-rita-bdobb v6.0.0 `scripts/build.sh` built `openbq-rita:6.0.0` from
openbq-org/agent-rita `f673c1f` plus patches 0001–0012, and `/status` and `agents.json`
answered 200. `docker compose ... build openbq-api openbq-mcp` built `openbq-local:6.0.0`, then
`openbq-mcp:6.0.0` on it (`pip check` clean, `obb.calendar OK`). MCP `initialize` opened a
session and listed the same 10 tool-discovery tools as `sha256:d76fbbac…`. Its catalog has
1,219 tools in place of 1,215: `econdb` (3), `fundamentals` (1) and `videos` (1) are new from
the v3/v4 base, and `calendar_trading_table` is gone with the separate calendar extension;
`calendar_trading` now comes from `v4/routes`.
