# v10 chart integration qualification — 2026-11-22

Implementation remains on isolated v10 branches. This receipt does not record a
public deployment. Exact KDB source is pinned in `v10/kdb/source.json` at
`647d7df4001a999dc83e6e2de57494ea78bf21d2`; its 58 tracked files were compared
byte-for-byte with the committed export. CLIENT vendors the matching HOST policy
through its established `gateway-vendor.mjs` process.

## Evidence

- KDB: 231 passed, 1 skipped (`tests q/tests`, with native q enabled). Runtime
  KDB-X 5.0, 2026.07.23 m64, native macOS arm64, Python 3.12.13/PyKX 4.2.0.
  Secured bootstrap, role dispatch, durable replay, accepted stream and FINOS
  diagnostics are exercised. Installed-wheel stdlib-only server smoke also passed.
- Deployment-pinned PyKX 4.1.0 plus HOST-locked pandas/NumPy/PyArrow: 38 native
  compatibility checks passed. A repeated export-only principal probe passed;
  actual EOD named calls produced Parquet preserving duplicate rows and 1ns times.
- Gateway: 182 passed. CLIENT preview server: 87 passed. Both test anonymous,
  session/credential, exact origin, target, ticket and bounded relay behavior.
- CLIENT: 61 focused chart tests passed and TypeScript typecheck passed. Earlier
  final implementation full suite: 9,072 passed, 47 skipped. Real lightweight-
  charts adapter is used by the renderer; these checks are not a deployed visual
  browser demonstration.
- HOST live-grid: 606 passed, 14 network tests deselected, with the native
  q/WebSocket/lifespan probe enabled against the final vendored source.
- HOST lake/export and Compose configuration: 18 passed. Compose was compiled
  without loading operator env files; target images were not built or launched.
- Independent review identified replay readiness and token ownership defects.
  Replay application errors now fail startup; torn-tail repair remains covered.
  Deployment instructions require live-grid's token to be owned by uid 10001.

The native HOST probe starts the secured q child, real owner-thread session/store
and a TCP WebSocket server. It checks authenticated discovery, snapshot, late
candle replacement, resume and normal autowired lifespan with diagnostic polling
and bounded shutdown. See `live-grid/tests/test_native_chart_stream.py`.

## Outstanding deployment gates

- Derived image startup on Linux amd64 and arm64 with the operator's licensed q.
- Actual Vercel session broker to Funnel WebSocket from outside the tailnet,
  including ticket expiry/reconnect, stalled client recovery and public q isolation.
- Full normal-load p95 accept-to-model latency and ingestion-regression comparison.

Follow [deployment instructions](chart-stream-deployment.md). No push, image
publication, Funnel activation, secret provisioning or Vercel deployment was
performed. Raw runtime/license output is deliberately discarded by wrappers;
application diagnostics are bounded operational telemetry, not durable audit
storage or a complete native password-rejection audit.
