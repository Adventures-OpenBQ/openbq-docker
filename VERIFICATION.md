# Episode 1 verification

Passed on October 5, 2026, on the x86-64 QNAP NAS. Release source is identified by tag `v1.0.0`; this is a local NAS image, not a published registry image.

- Docker `27.1.2-qnap8`; Compose `v2.29.1-qnap2`.
- Final locked image: `sha256:4b6bbfc98174821d97c3b33cd5c7eaa908f6e6cd91a3939ab6437a6bc420d96f`.
- Python base: `python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d`.
- Exact installed package inventory: `requirements.lock`; `pip check` returned no broken requirements.
- After force-recreating both containers, the API became healthy. From the Mac over private Tailscale HTTPS, smoke passed: 927 widgets, 1,148 schema paths, app/agent catalogues, and one nonempty CBOE AAPL quote result.
- HTTPS catalogue access passed and raw sidecar port 6900 was unreachable. NAS LAN and tailnet port 6900 also rejected connections; Docker reports no published API ports.
- Markers in both settings and OpenBBUserData volumes survived recreation. The dedicated Tailscale node retained its node ID, domain, and IP.

Initial API route discovery took about two minutes; the proxy can return 502 before the API is ready. Initial certificate issuance encountered a Tailscale control-plane timeout and subsequently succeeded. A temporary sidecar MTU experiment was reverted to 1500 before successful tests; it is not a required configuration or a proven fix. No NAS firewall changes were made. A subsequent HTTPS size check successfully downloaded the full widget catalogue (4,927,924 bytes) and OpenAPI schema (8,424,773 bytes).

This verifies one supported data route and this NAS architecture. Workspace/browser compatibility belongs to Episode 2. See the [series rehearsal report](https://github.com/artcashin/adventures-in-openbq-articles/blob/v1.0.0/editorial/rehearsals/v1/REPORT.md).
