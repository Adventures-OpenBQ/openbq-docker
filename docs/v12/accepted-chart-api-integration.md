# Accepted chart API integration on v12

This branch ports the accepted-data API onto the existing v12 feature line. It
retains Art's Charts, TemporalDB, composed studies and the explicit legacy live
paths. It does not deploy the branch or change a running service.

Sources: accepted API integration `93aa2c9` (the qualified v10 changes through
`031e608`, with main integration corrections), plus transport correction
`d16b71d`. The v12 starting point is `5df534a`. The secured KDB vendor remains
`647d7df4001a999dc83e6e2de57494ea78bf21d2`; every one of its 58 tracked source
files was compared byte-for-byte with that commit.

The gateway has distinct bounds for Art's existing study socket and the accepted
chart stream. `/grid/chart_stream_ws` uses origin-bound, single-use tickets and
an 8 MiB upstream WebSocket parser. Client controls remain bounded to 64 KiB.
The real parser regression failed at the old 64 KiB ceiling, then passed at
128 KiB, 512 KiB and 8 MiB, with 8 MiB + 1 rejected. Existing v12 gateway tests
remain part of the regression run.

Opt-in deployment uses `compose.chart-stream.yml`; its quoted tmpfs value is
preserved. Compose compilation checks that q has no published port, remains on
the private network, and named clients load their own credential files. No q
credential is sent to the browser. Diagnostics, durable recorder handling and
the named EOD exporter use the same qualified source as the earlier integration.

Verification before the API integration commit:

- Gateway: 213 tests passed, including existing charts and TemporalDB routes.
- Live-grid: 628 tests passed, with 1 optional native probe skipped and 14
  network tests deselected; the native probe was run separately below.
- Native q: the real HTTP/WebSocket probe passed using the shipped KDB vendor,
  including snapshot, late candle replacement, quiet resume, autowired lifecycle
  and diagnostics shutdown.
- Compose and named exporter: 3 tests passed.

The separate v12 consumer qualification covers embedded Art's Charts, study and
anchor semantics, rendered session alignment and its final vendor pin. The
transport and native probe above do not establish those consumer guarantees or
replace the remaining cross-platform load gates.
