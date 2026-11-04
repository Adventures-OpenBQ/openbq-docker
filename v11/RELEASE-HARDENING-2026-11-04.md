# v11 release hardening — November 4, 2026

The NAS deployment and browser CI are qualified separately from dependency
hardening, signed distribution and public Vercel access. This record tracks the
remaining release work without changing the deployed images or rollback.

## Dependency triage

Reviewed client source: `2ee88d18b217eb44589468064ee27350bd60699c`.
GitHub reported 29 open dependency alerts at review time. None was dismissed
or treated as fixed by this review.

| Dependency | Evidence and disposition |
| --- | --- |
| PDF.js 5.7.284 | The advisory requires PDF scripting enabled. `PdfView.tsx` creates `PDFViewer` without a scripting manager; the installed viewer defaults that manager to null and computes `enableScripting` from its presence. Scripting is therefore disabled in this integration. Preserve that boundary. An upgrade to major 6 would change the supported Safari baseline; do not silently drop the documented iPadOS 16.4 support. |
| MapLibre 4.7.1 through Plotly | The advisory concerns untrusted attribution HTML in a map control. The app's partial Plotly bundle registers scatter, candlestick, bar, heatmap and treemap only. All 13 JavaScript source maps in the retained `client-4dc87f7f/browser` artifact were inspected: none lists MapLibre JavaScript sources. This supports absence from that artifact, not a universal exemption for future map widgets or future bundles. Verify final rebuilt artifacts too. |
| rustls 0.23.43 | The advisory fixes require 0.23.46. Prepare a compatible lockfile update, refresh dependency/license evidence and requalify desktop artifacts before claiming resolution. |
| glib 0.18.5 | The fix crosses to 0.20. Check the Tauri/GTK dependency chain and supported platform exposure before changing it. |
| Vitest, mocker, tinypool, Vite, source-map-js, esbuild, minimatch | Development/build dependency findings remain open. Qualify compatible updates together; do not assume a transitive major-version override preserves test-runner behavior. Keep development servers private during this work. |
| regex in archived unic-ucd-ident manifests | The alerts point to historical dependency-evidence manifests. The actual desktop Cargo lockfile uses regex 1.13.1. Preserve the original third-party evidence; record its provenance rather than editing it to hide an alert. |

Primary advisories: [PDF.js](https://github.com/advisories/GHSA-hq66-cqwq-w95j),
[MapLibre](https://github.com/advisories/GHSA-jrc7-96c5-q579).

The focused PDF legacy, PDF viewer and Plotly suites passed **51 tests** during
this review. They establish current compatibility and behavior, not an exploit
test or a replacement for the full browser gate.

The main client checkout currently shares a dependency directory with the
qualification workspace. Any installation or dependency update must first use
an independent dependency directory to preserve the qualified artifacts.

## Public demo

The NAS routes remain authenticated tailnet services. Internet Funnel remains
disabled. Local CLI/project discovery and the current repository deployment API
did not identify the project. Read-only inspection of the existing Vercel
dashboard then confirmed project `bdobb-dev/openbq-bdobb`, serving
`https://bdobb.openbq.secretoftheuniverse.com`.

Its production branch is `main`, but its connected repository is
`Adventures-OpenBQ/bdobb-private-archive-20261025`. The production deployment is
Ready at October 24 commit `7928f72c4c63c449793dd3f81e25ebb34100cb41`
(v10), deployment `GFyfQyfWUTCZ2A7diXcw8Jh2FPht`. The Git settings independently
confirm that archived repository connection. Current public-repository main
pushes therefore do not update this project. No connection or deployment was
changed during this inspection. Reuse this project and domain when preparing
the v11 deployment; preserve its existing production rollback. A configured
custom preview domain is not evidence of an incorrect Vercel origin.

Read-only build-settings inspection also found Node 22, no framework command
overrides, and a custom ignored-build command that builds production but skips
non-production deployments. A preview qualification will need that existing
skip rule accounted for; it must not be mistaken for a failed source build.

Before publication, validate the actual OAuth identity/allowlist, exact origin,
private relay credentials, principal/scope mapping and end-to-end retained-result
queries. Do not substitute a shared operator identity for the authenticated
viewer. The existing gateway `/mcp` route must not be assumed to serve TemporalDB
MCP; the dedicated TemporalDB MCP endpoint is currently tailnet-only.

## Remaining distribution gates

* Build final macOS, Windows and web artifacts from the selected source; retain
  artifact hashes and platform-specific verification.
* Reconcile the source offer, notices and license evidence with those exact
  artifacts. TemporalDB remains private and separately licensed.
* Sign and publish the v11 release only after those gates pass. The published
  v10 release is not evidence that v11 has been signed or published.
* Retain the rehearsed rollback and a verified off-NAS recovery copy. A copy of
  the qualification snapshot is not a scheduled backup of subsequent live data.

## Vercel reconnection and staged build

After explicit approval, the existing project's Git connection was changed to
`Adventures-OpenBQ/bdobb`. The dashboard confirmed the new connection. Production
still tracks `main`. Automatic assignment of production domains was disabled
and its saved state rechecked after reconnection, so new builds require manual
promotion and the v10 deployment remains the rollback target.

A staged production build was started for exact commit
`2ee88d18b217eb44589468064ee27350bd60699c`:
[deployment BFB6cWQKPTQS6Qiq9vPFhzymM1j6](https://vercel.com/bdobb-dev/openbq-bdobb/BFB6cWQKPTQS6Qiq9vPFhzymM1j6).
Its initial status is Building; initiation is not successful deployment or
public-demo acceptance.

Fresh local verification passed all **94 web relay tests** and `pnpm build:web`.
The generated output has no public `static` directory, sends every route to the
private Node 22 function, and contains no MapLibre markers in its 13 JavaScript
assets. Marker absence is supporting evidence, not a general vulnerability scan.

Read-only inspection found existing production authentication, gateway, news,
Rita and MCP variable names, but no `TEMPORALDB_V11` or `TABLE_RELAY_TOKEN`.
Secret values were not revealed. The live gateway's preview origin matches the
existing custom demo domain. Completing TemporalDB browser functionality still
requires the private relay setting, verified public ingress and real principal
binding; source reconnection alone does not supply those prerequisites.

## Off-NAS recovery copy

The rehearsed final `9a1cf6f` recovery snapshot and current cutover bundle were
copied to a private, owner-only directory on the development Mac. Every regular
file in each local TAR was checked against a fresh SHA-256 inventory from its
NAS source: **21 recovery files and 66 cutover files matched**. Credentials and
private configuration remain outside Git. The local archive hashes are:

* Recovery: `d0212c2536c9a35ac84e222359b640cff4a8ecab0ee9a00405ca9467f9f4d7e5`
* Cutover: `9a125b7c7b74ef28c55947820bb64f1e96fb2c96cb3a6d1c6046c49fe7cabc05`

This verifies transfer integrity of the previously rehearsed snapshot; it does
not claim a new restore from the local copy or backup coverage of later writes.

See [live deployment and rollback](NAS-LIVE-2026-11-04.md) for the qualified
runtime and [final qualification](FINAL-QUALIFICATION-2026-11-04.md) for its
bounded acceptance evidence.
