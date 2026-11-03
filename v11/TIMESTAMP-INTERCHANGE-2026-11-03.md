# v11 timestamp interchange slice

Source changes only; no release image, desktop artifact, provider pin or source
offer was rebuilt. Existing installed qualification receipts describe the earlier
artifact, not this change. No deployment or main merge was performed.

## Actual v11 paths

The later handoff hooks (`useSeriesBars`, `useStudySeries`, `series_payload.py`)
are not in this v11 assembly. The active client uses `src/lib/liveChart.ts`;
the host uses `/series`, `/chart` and Plotly `/ta_chart` plus its websocket delta.

- `live-grid/app/market_time.py`: the known legacy-naive-UTC adapter; normalize
  explicit offsets to UTC before removing timezone for the existing engine.
- `/series`, `/chart` and tick history: emit explicit UTC for intraday instants;
  preserve daily market-date labels. Do not mutate cached/internal rows.
- `app/ta/payload.py`: normalize offset-aware inputs before constructing the
  existing naive-UTC study frame. Internal timezone/session policy is unchanged.
- `app/ta/figure.py`: full/delta dates use the same interval-aware wire policy.
  Seam comparisons normalize offsets; daily seam shapes retain date labels.
- `app/series.py:window_end`: offset-aware request ends compare on the existing
  naive-UTC internal clock instead of mixing aware and naive datetimes.
- `app/static/demo.html`: range reader respects offsets/UTC and preserves
  seconds/milliseconds; it rejects invalid calendar/time values.
- Client `src/lib/marketTime.ts`: explicit offsets, UTC, daily dates and the
  documented legacy-naive-UTC bar contract; reject JS rollover dates. This is
  a chart projection, not a lossless evidence representation.

Wire timestamps accept ISO calendar dates and times with optional seconds,
up to six fractional digits and explicit UTC/numeric offsets. Unmarked timestamp
acceptance is limited to this known bar boundary, not arbitrary provider wall
clocks. The internal frame supports microseconds; finer precision is explicitly
refused, not silently truncated. Browser numeric projections use JS millisecond
precision and do not replace retained source evidence. New epoch encodings were
not introduced.

## Verification

Host: 155 targeted Python tests passed; 14 opt-in parity cases deselected by the
existing test configuration. The host test image is a disposable derivative of
local `openbq-live-grid:10.0.0` with pytest 9.0.2 and pytest-asyncio 1.3.0; it is
not a release artifact. Tests mount the actual isolated host and kdb sources and
run with external networking disabled. Browser range reader: 16 Node cases pass.
Client: 67 conformance/bar/renderer tests pass in each of Honolulu and Tokyo;
TypeScript passes. Independent review found and verified the daily positive-offset
fix; the reviewer reran 43 host cases with no further findings.

The fixture is duplicated deliberately so each repository remains independently
testable/packageable. Its bytes must agree across client and host:
`24d7687f7edb360460a5d58eda461e69cfece8a20b24a1002516110d2ea4e138` (SHA-256).

## Remaining calendar/reporting work

No display-zone defaults, session membership, auction rules, receipt schemas,
calendar fallback or portfolio valuation policy changed. The richer calendar
source response/coverage audit and retained dated-session integration follow.
Reporting/session-boundary behavior remains unaudited; do not claim a reporting
bug was established or that historical calendar evidence is already retained.
