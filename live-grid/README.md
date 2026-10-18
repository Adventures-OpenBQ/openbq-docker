<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# live-grid

> **On openbq-docker (v10).** Ported from bdobb-dev/openbb-docker v10.1.7 (`d606169`); the
> per-file record is [docs/v10/live-grid-kdb-port.md](../docs/v10/live-grid-kdb-port.md).
> Differences from the text below, which is the donor's:
>
> - It runs only under the opt-in `live` compose profile (`docker compose --profile live up -d`),
>   with the `openbq-kdb` service beside it. It has no host port and no Serve entry; BDOBB's web
>   preview reaches it through the funnel-gateway's `/grid` family (the `web` profile, with
>   `"liveGrid": true`).
> - It loads `credentials.env` (`EODHD_API_KEY` and the `OPENBB_API_*` pair); this line has no
>   `api-auth.env` and commits no key, not even EODHD's public demo key (`scripts/smoke.py`
>   reads `EODHD_DEMO_WS_KEY` from the environment).
> - The image runs as uid 10001 with a read-only root (`/data` and `/tmp` are the only
>   writable paths). A `live-grid-data` volume created by an earlier root-run build is owned
>   by root; the one-shot `live-grid-perms` service gives it to uid 10001 before live-grid
>   starts, on every `up`, so no manual step is needed.
> - History comes from openbq-api's EODHD namespace (`OPENBB_HISTORY_NAMESPACE=eodhd`, so
>   `/api/v1/eodhd/<class>/price/historical`, provider `eodhd`), because openbq-api has no
>   standard routers and no openbb-kdb read-through provider. There is no kdb history cache:
>   kdb holds the live ticks only. `provider=kdb` on `/series`, `/chart` and `/ta_chart` is
>   accepted and served from EODHD; EODHD's history intervals are 1m, 5m, 1h and 1d.
> - Tests: `pip install -e ../v10/kdb/source` plus the dev extras, then `pytest` (no licence, no q,
>   no network; `-m network` holds the live EODHD parity checks, which skip without a key).

OpenBB Workspace `live_grid` backend streaming real-time **EODHD** prices —
US equities, crypto and forex in one watchlist. Companion code for
*Adventures in OpenBB, Ep. 9*, extended in **Ep. 10** with tick recording and
a chart that joins cached history to bars built from the live feed.

- `GET /widgets.json` — the widget contract (`live_grid`, `live_chart`,
  `kdb_cache_chart`, `ta_chart` and `kdb_ticks`).
- `GET /live_grid?symbol=A,B,C` — initial rows, seeded from REST snapshots
  (previous close is cached as the change baseline).
- `WS /live_grid_ws` — Workspace sends `{"params":{"symbol":"A,B"}}` on
  connect and on every param change; the backend streams one row dict per
  update, coalesced to ~4 flushes/second per connection.
- `GET /snapshot?symbol=AAPL` — one symbol's delayed REST snapshot (EODHD,
  15-20 minutes behind), for callers that want a quote without the live feed.
- `GET /health` — per-feed connection state and `feeds_bad_messages` (feed
  messages that could not be applied, skipped). `status` is `degraded`, with a
  `tasks` block naming the error, while the feed manager or the lease sweeper
  crashed in the last 5 minutes; both are restarted with backoff and logged at
  ERROR. Plus a `ticks` block
  (`buffered`, `written`, `dropped`, `spooled`, `replayed`, `deduped`,
  `quarantined`, `endpoint`) when the chart is enabled; see "The tick spool" below.
- `GET /chart?symbol=AAPL&interval=1d` — Plotly figure JSON, the Workspace
  `kdb_cache_chart` widget.
- `GET /series?symbol=AAPL&interval=1d&start=&end=` — `{bars, cache}` for
  incremental loads; `cache` reports `rows_from_cache`, `rows_from_upstream`,
  `rows_from_ticks` and a `seam` timestamp (see below).
- `GET /ta_chart?symbol=AAPL&interval=1d&...` / `WS /ta_chart_ws` — indicator
  chart over cached OHLCV in stacked panes, the Workspace `ta_chart` widget.
- `GET /ticks?symbol=AAPL&limit=200` — the newest ticks held in the kdb+ tick
  cache for one symbol, newest first; the Workspace `kdb_ticks` widget.
- `GET /subscriptions` — the subscriptions management page (see
  `POST /subscribe` below).
- `GET /demo` — a standalone scroll page for the chart, moved here from the
  now-removed `cache-chart` service.

### Symbols

Symbols are bare, as the feeds take them: `AAPL`, `BTC-USD`, `EURUSD`, `^GSPC`.
An exchange suffix naming the symbol's own feed is dropped (`AAPL.US` → `AAPL`,
`BTC-USD.CC` → `BTC-USD`, `EURUSD.FOREX` → `EURUSD`); anything else the EODHD
websocket SDK refuses (another suffix such as `AAPL.LSE`, `BRK.B`, a space) is a
`422` on `/subscribe` and `/api/subscriptions`, and is dropped from `/live_grid`,
`/symbol_meta` and `live_grid_ws` params. If a refused symbol still reaches a
feed (an old watchlist file), it alone is left out with one warning and the
rest of that feed starts.

### `POST /subscribe`

Leases a live feed for symbols, keyed by symbol and renewable:

    curl -X POST http://127.0.0.1:6903/subscribe \
      -H 'content-type: application/json' \
      -d '{"symbols":["AAPL"],"ttl":300}'
    {"leases":{"AAPL":"2026-08-26T15:20:00+00:00"}}

Posting a symbol that is already leased extends its expiry rather than adding
a second registration. Leases lapse after their TTL unless renewed; a sweeper
drops them. Tailnet-only, like every route here — never funnel it.

Leasing a symbol that is not already fed rebuilds its EODHD feed, because the
SDK fixes symbols at construction. That briefly interrupts ticks for other
symbols on the same feed, which is why the TTL is generous rather than tight.

Symbols route by shape: a dash means crypto (`BTC-USD`), two ISO currency
codes mean forex (`EURUSD`), everything else is a US equity. Feed clients are
rebuilt (debounced ~1s) when the subscribed union changes; the SDK's
signal-handler and grow-forever-buffer quirks are handled in `app/feeds.py`.

All three lease values are configurable: `ttl` per request in the `/subscribe`
body (default 300s -- `LIVE_GRID_LEASE_TTL_S`), and `LIVE_GRID_LEASE_SWEEP_S`
(default 30s) for how often the sweeper checks for lapsed leases. `/health`
reports the current lease count.

## Tick recording and the chart (Ep. 10)

Every trade this service already receives over the websocket is now also
recorded into whichever q the same **`openbq-kdb`** resolution chain finds —
on openbq-docker, the **`openbq-kdb` service**, reached at `openbq-kdb:5000`
on the internal `live-private` network (`KDB_BIND_HOST=openbq-kdb`; no host
port, and this container never spawns its own q: `KDB_EMBEDDED=false`). See
[openbb-kdb/README.md](../openbb-kdb/README.md#configuration) for the full
chain (bring-your-own q dropped in `./kdb`, then loopback, then `KDB_HOST`) —
this service's `KDB_EMBEDDED=false` only opts it out of the *spawning* step,
so it always joins a q something else provides. `GET /health` reports which
link resolved, under `ticks.endpoint` — `"spawned"`, `"loopback"`, or
`"<host>:<port>"` — so you can tell which one is actually in use without
guessing. Ticks accumulate in a bounded in-process buffer
(`app/recorder.py`) and are flushed to q as one batch on the existing
~250 ms cadence — per-tick IPC would not keep up. On overflow the buffer
drops the oldest tick, counts the drop, and reports it on `/health`.

### The tick spool and the reconnect backoff (openbq-docker v10)

A user ruling (2026-10-12) requires that ticks be spooled to the filesystem
and recovered when a service restarts. The Mac crash drill had shown live-grid
dropping ~100 s of crypto ticks while kdb was down, then waiting out a fixed
60 s retry latch. Details, tests and the drill are in
[docs/v10/live-grid-kdb-port.md](../docs/v10/live-grid-kdb-port.md#tick-spool-and-fast-reconnect-user-ruling-2026-10-12).

- **Spool.** A batch kdb does not acknowledge goes to `app/spool.py`'s files
  under `LIVE_GRID_SPOOL_DIR` (compose: `/data/spool`, on the `live-grid-data`
  volume; default: a `spool/` directory beside `LIVE_GRID_WATCHLIST`), one
  JSON array per line, `ticks_<UTC date>_<seq>.jsonl`. While the spool holds
  anything, new ticks join its tail, so kdb receives them in arrival order.
  Each flush replays it, oldest first, up to 5,000 ticks per write and about
  1 s per flush. A file is deleted only after kdb confirms every line in it.
  Leftovers are replayed on the first flush after startup, and a graceful
  stop spools the unflushed buffer.
- **No duplicates.** A segment is staged on disk (`spool.state`) before it is
  sent. A segment that may already have reached kdb is in doubt: one staged
  when live-grid died, or one whose write raised after sending. openbq-kdb's
  `ticks_present` probes kdb for it, and it is skipped (`deduped`) when kdb
  already holds every row, for instance after persist.q replayed it at boot.
- **Bounded.** `LIVE_GRID_SPOOL_MAX_MB` (default 256, about 44 h at 24 ticks/s).
  Past it, new ticks are dropped, logged and counted in `dropped`. The disk
  is never filled silently.
- **Durability.** Every append is written through to the OS, so a killed
  live-grid loses nothing it spooled. fsync runs at most once per
  `LIVE_GRID_SPOOL_FSYNC_S` (default 1 s), so a host crash costs at most about
  that long. The cursor is fsynced whenever it changes, which is once per
  replayed segment.
- **`/health` `ticks`.** `spooled` is the number of ticks on disk now.
  `replayed` and `deduped` count since start. `written` includes `replayed`.
  `dropped` counts only ticks truly lost: buffer overflow, the cap, or a
  spool I/O error. `quarantined` counts ticks in `spool/quarantine/`. A
  segment whose send raises (an error from q, not kdb being down) is resent
  with exponential backoff (1 s doubling to 60 s), and only after 8 failed
  sends spanning at least 60 s of wall clock is it moved there, so newer
  ticks can flow; an error that clears sooner loses nothing. A refusal from
  kdb's tick log (`tlog: …`, persist.q, while its disk is full) is not such
  an error: q applied nothing, so it is backed off like a connection failure
  (1 s doubling to 15 s) and never counts toward quarantine, however long the
  disk stays full. The count, the failures and the first failure's time
  survive restarts. A quarantined segment is up to 5,000 rows and may hold
  good ticks spooled behind the bad one. To re-send a file: stop live-grid,
  move it into `spool/` as `ticks_9999-12-31_<six digits>.jsonl` (sorts
  after every live file, so the replay cursor is undisturbed), and start
  live-grid; it is replayed after the backlog, out of time order.
- **Reconnect backoff** (openbq-kdb `session.py`). After kdb stops answering,
  live-grid retries after 1 s, doubling each time, capped at 15 s
  (`KDB_RETRY_INITIAL_S`, `KDB_RETRY_MAX_S`). This replaces the fixed 60 s
  latch. Calls inside the window still fail fast without dialling.

**Retention is a rolling window**, `LIVE_TICK_WINDOW_SECONDS` (default
86400 = 1 day; openbq-docker's compose sets 172800 = 2 days, so eod-dump's
00:05 flush and its hourly retries still find the whole UTC day). A pruning
pass drops ticks older than the window so a busy feed's tick storage cannot
grow without bound or compete with the historical cache under its own LRU.

**The seam.** A chart request stitches cached history to tick-derived bars at
the first bar boundary *fully* covered by ticks — not the first tick itself.
The bar straddling that boundary would be missing its own opening trades if
aggregated from ticks alone, so it comes from history instead; ticks own only
the bars they cover completely. `/series` reports the seam timestamp and
`rows_from_ticks` whenever ticks contributed to the response, and the joined
series is strictly time-ordered with no duplicate timestamps across the seam.

**The two sources will not agree exactly**, and this is inherent, not a bug:
vendor bars are consolidated across venues and adjusted after the fact, while
this service's bars are aggregated from whatever prints its own websocket
connection happened to receive. Closes track closely near the seam; **volume
in particular can differ visibly**, since a vendor's consolidated tape counts
trades this feed never saw. Don't expect — and don't advertise — a seamless
match; the seam marker exists precisely because the two sides are different
data.

**Turning it off.** Set `LIVE_GRID_CHART=false` (or leave kdb+ unreachable —
recording degrades to a logged warning, and ticks wait in the spool up to its
cap) and `live_grid` / `live_grid_ws`
behave exactly as they did before Ep. 10; `/chart` and `/series` still serve
history-only data with no ticks contributed.

## Keys

`EODHD_API_KEY` — the public demo websocket key in `.env.example` covers
exactly the default watchlist for testing. Real watchlists need a paid EODHD
key with websocket access (free-tier keys 403 on connect; the REST-only
`demo` token fails the SDK's key-format validation).

### Authentication

With `OPENBB_API_AUTH=true`, every live-grid surface — REST routes, the
subscriptions page and both websockets — requires HTTP Basic auth. The
credentials are `OPENBB_API_USERNAME` and `OPENBB_API_PASSWORD`, the same pair
openbq-api uses; on openbq-docker compose loads them into live-grid from
`credentials.env` (this line has no `api-auth.env`), so there is one
credential to rotate for the stack's HTTP surfaces. Auth is **off by
default**: `credentials.env.example` leaves `OPENBB_API_AUTH` empty, and then
anything on `openbq-internal` can reach `/api/subscriptions`, `/subscribe`
and the websockets. live-grid logs a warning at startup when it runs open.
Set all three in `credentials.env` to turn the guard on.

The guard is off only when `OPENBB_API_AUTH` is unset, or set to anything
other than `1`, `true`, `yes` or `on` (case-insensitive) — `false` counts as
"set" but still disables it. That's what local development and the test
suite rely on.

A CORS preflight is answered without credentials — the guard is registered
inside the CORS layer deliberately. A browser preflight carries no credentials
by definition, so an auth layer outside CORS would answer it with a bare 401 and
lock out every cross-origin client while curl still worked.

Note for the subscriptions widget: it is declared `type: iframe`, and the
desktop client renders an iframe widget as a plain `<iframe src>` navigation
with no headers — the Connection's configured `Authorization` header is
attached only to fetch-path requests, which iframe widgets do not make. So with
auth enabled the widget's initial page load receives a 401 that the client
cannot satisfy. Resolving that is a design question, not a configuration one:
the options are exempting the page (its API stays guarded), moving the widget
off `type: iframe`, or adding a credential the iframe can carry. Until one is
chosen, the subscriptions widget does not work through the guard — and since auth is on by default in
this stack, that is the widget's default state, not an opt-in one.

## Test

    pip install -e .[dev] && pytest          # all mocked, no key, no kdb+ needed
    python scripts/smoke_live.py             # real key: crypto feed, 24/7

The aggregation query itself (`` `time xasc `` before bucketing — ticks
arrive out of order and an unsorted trades table silently produces wrong
candles) is verified against a **real** q by
[`v10/kdb/source/scripts/tick_check.py`](../v10/kdb/source/scripts/tick_check.py), not
by anything mocked here. See that script and `v10/kdb/source/README.md`.

## Technical Chart (`ta_chart`)

Indicators over the same cached OHLCV the other charts use, in stacked Plotly
panes. 22 tier-1 indicators; 12 of them can also be drawn from EODHD's own
pre-calculated values by setting `source=eodhd`, and every one of those 12 is
checked against EODHD's numbers by a network-gated parity test.

CCI is deliberately local-only. EODHD's CCI disagrees with the standard
definition by a median of 28.5%, so offering both sources for it would mean the
line jumped when you toggled `source`. It computes locally and says so in the
legend.

Layouts are **macros** — YAML files in `macros/`, one pane per entry:

```yaml
label: Classic Momentum
panes:
  - id: price
    height: 3
    indicators:
      - {name: bbands, period: 20, k: 2.0}
  - id: rsi
    height: 1
    indicators: [{name: rsi, period: 14}]
```

`height` is a relative weight. Exactly one pane must have `id: price`. Drop a
file into `TA_MACRO_DIR` and it appears in the widget's Macro dropdown without
a rebuild — `/widgets.json` is generated, not static.

Indicators can also be listed directly:
`?indicators=rsi:period=14,sma:period=200`.

**On `source=eodhd`:** EODHD bills five API calls per indicator per request, so
those series are cached and refreshed only on bar close (`TA_EODHD_MIN_REFETCH_S`).
Locally computed series update at tick speed; EODHD-sourced ones step. Any
indicator without an EODHD equivalent falls back to local compute and says so
in the chart title. EODHD's technical endpoint is daily only, so on any
interval other than `1d` the whole request is computed locally and annotated
rather than fanning one daily value across every bar of the day.

Smoke check: `python scripts/smoke_ta.py http://127.0.0.1:6903`

### Subscriptions widget

`GET /subscriptions` serves a page, declared in `widgets.json` as an `iframe`
widget, that manages the EODHD live subscription list. Its API:

    GET    /api/subscriptions              current state
    POST   /api/subscriptions              {"symbol": "AAPL"} -> 201
    DELETE /api/subscriptions/{symbol}     -> 200

Pinned symbols persist in `LIVE_GRID_WATCHLIST` (default `/data/watchlist.json`,
which needs the `./live-grid-data:/data` mount) and are re-registered with the
feed manager at startup, so a restart restores the subscriptions rather than just
the list.

`LIVE_GRID_MAX_SYMBOLS` (default 50) caps the account-wide EODHD budget. The
count is everything actually subscribed at EODHD right now — pinned, leased,
*and* whatever a `/live_grid_ws` grid connection has registered, all read off
the feed manager's own view, so a symbol subscribed twice over is still one
slot. An add that would exceed the cap returns 507. Leased symbols appear in
the widget but cannot be removed there — they lapse on their own TTL. A
watchlist file with more symbols than the cap only has the first `cap` of
them (sorted) registered at startup; the rest are logged as dropped.

An `iframe` widget's endpoint must be an absolute URL. `/widgets.json` uses
`LIVE_GRID_PUBLIC_URL` when it is set (e.g.
`https://openbb.<your-tailnet>.ts.net:6903`); unset or empty, it uses the
scheme and host the request came in on, so any address a client reaches
live-grid at loads the page without configuration. Its writes (add, remove)
then work only on a loopback host (a local relay): set `LIVE_GRID_PUBLIC_URL`
for any other direct address. `X-Forwarded-*` headers are not consulted. Behind a direct HTTPS tailnet Serve (TLS ends before live-grid, so it sees plain
HTTP) you must set `LIVE_GRID_PUBLIC_URL` to the `https://` address: otherwise the iframe URL
comes out `http://` and the page's POST/DELETE writes get 403 on the Origin check.
`/health` reports `"subscriptions": {"published": true}`.

Why a variable at all, when every other widget just uses the Connections base:
bdobb hands an `iframe` endpoint to `new URL(raw)` with no base, so a relative
path is refused outright. A *data* widget's endpoint is joined to that base and
needs nothing. A Tailscale `svc:` name would not change this — it would only
supply a nicer absolute URL, and the variable exists because an absolute URL is
required at all.

**The widget works today**, by two mechanisms that fit together:

* `/subscriptions` (the page) is **exempt** from the auth guard — a browser
  frame issues its own navigation and cannot attach a header, so under a
  blanket guard it would 401 and paint blank. The page carries no data.
* `/api/subscriptions` (everything it does) **stays guarded**. Once loaded, the
  page asks its host for credentials over the `openbb-connect` / `openbb-auth`
  postMessage handshake and sends them on every call.

So a bare `curl /api/subscriptions` returning 401 is the guard working, not the
widget failing.

`docs/superpowers/specs/2026-08-27-authenticated-page-widget-design.md` designs a
`page` type that would replace *both* mechanisms with one: fetched rather than
framed, so it needs no exemption, no absolute URL, and no handshake. **It is not
implemented in bdobb-v2 yet.** Until it is, the exemption and this variable are
both load-bearing — and switching the widget to `type: html` in the meantime
would be a regression, not a shortcut: a `srcdoc` frame has an opaque origin, and
the resulting `Origin: null` is refused by the origin check on `POST`/`DELETE
/api/subscriptions` described below.

Tailnet-only, like every route here. Never funnel it. `POST`/`DELETE
/api/subscriptions` additionally reject a request whose browser `Origin`
header does not match `LIVE_GRID_PUBLIC_URL` (unset: the request's own scheme and
host, the origin the page was framed from, and only on a loopback host, since a
DNS-rebinding page controls both Host and Origin; a request with no `Origin`,
e.g. curl, is unaffected) — CORS here is wide open for the Workspace origin's
reads, and this keeps some other page an operator has open from silently
mutating the durable watchlist.
