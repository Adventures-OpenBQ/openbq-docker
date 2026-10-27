# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""One bar source for the card, its studies, describe_chart, snapshots and the worker.

`ComposedBars(symbol, interval, start, end, provider, session, fresh) -> (bars, meta)`
takes history from the chart's provider (an ODP source per provider) and, when
live-grid covers the symbol, replaces the current session with live-grid's bars:

- The seam is the session open from the exchange calendar (UsEquitySessions):
  the extended open (04:00 New York) for an intraday chart, the regular open
  for a `session=regular` one and for `1d` (today's daily bar is the regular
  session, as a vendor's is); the UTC day for crypto and forex.
- live-grid's minutes from the seam are folded into the chart's interval the
  way the providers stamp their own history (sampled 2026-10-23): each segment
  of a US day -- pre-market from 04:00, regular from 09:30, after hours from
  the close -- is bucketed from its own start, and no bar crosses a segment
  edge. So a regular-session hour is 09:30-10:30 (yfinance and EODHD), its
  last bar 15:30-16:00, and after-hours hours start at 16:00 (EODHD's 20:00Z
  bar, yfinance's prepost 16:00). A crypto or forex day is one segment.
- For a covered symbol no history request reaches the current session (the
  quota guard, ruling L9): history ends the day before.
- An intraday chart whose session is not `regular` (extended, 24hr) takes its history
  from the provider's extended source when it has one -- yfinance asked with
  `prepost=true` (user ruling 2026-10-26, step 1 Q5) -- so earlier days carry pre-market
  and after-hours bars, stamped in the same three segments as today's live bars (step 1
  F8). EODHD has none: its history is unchanged. The pacer is keyed on that choice, so a
  regular and an extended chart never share an answer.
- live-grid restarted mid-session (its span starts after the seam, or it holds
  nothing past the open): live-grid's bars start at the first bar the span
  fully covers, the chart shows a gap before it, and `meta.live` is "partial".
- A covered `1w` or `1M` chart's current period (spec L10, every provider) is
  rebuilt from the provider's own `1d` bars from the period's start to yesterday,
  plus today's live daily bar, stamped with its first day as Gold's resampled
  periods are; the provider's own bar for that period is dropped (it may hold
  today's vendor data). The period's adjusted close is then None: today's close
  stands in, as on the daily chart.
- Not covered, not configured, down, refusing, without the §4 route, a
  non-session day, a window that ends before today, or a `5d` interval:
  history alone, `meta.live` false. Never an error.

`meta.live_reason` says why `live` is false (user ruling 2026-10-26), and is None when it
is true or "partial" (a late span is partial's one cause): "no_session" -- today is not a
session this chart shows live (a non-session day, a window without today, `5d`);
"unavailable" -- live-grid is not configured, down, refusing, without the §4 route or
answering a malformed tape; "not_covered" -- live-grid answered and does not hold the
symbol. Checked in that order, so a weekend reads "no_session" whatever live-grid says.

`meta.live_volume` is "venue" when today's bars are live-grid's (`live` true or "partial";
a covered week or month too): live-grid's feed is one venue's trades (its EODHD socket is
EDGX-only), so today's volume is a small fraction of the consolidated volume history
carries. The bars keep it -- the price is right -- and the flag lets the card and Rita say
so (user ruling 2026-10-26). None otherwise.

`meta.forming` is the last bar's stamp (as the snapshot payload's candle time
spells it) while that bar is still forming, else None. History is paced per
question (HistoryPacer: one bar, at most 15 minutes, with its backoff); a
repeated question with nothing new answers the SAME object, so a study socket
pushes only when something moved.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from arts_charts.calendar import XNYS, ExchangeCalendar, UsEquitySessions
from arts_charts.classify import classify
from arts_charts.conditions import bar_end
from arts_charts.history_pacer import HistoryPacer, interval_step
from arts_charts.live_grid import LiveGridBars, Tape, utc
from arts_charts.odp_bars import NotConfigured
from arts_charts.temporal_gold import DAILY_ONLY, resample
from arts_charts.temporal_gold import INTERVALS as TEMPORAL_INTERVALS
from arts_charts.ta.session import _naive_utc, is_intraday

BarSource = Callable[[str, str, str, str], Awaitable[tuple[list[dict], dict]]]

#: The answer when the window holds no history to ask for (live from the window's start).
NO_HISTORY: tuple[list[dict], dict] = ([], {})
#: Intervals whose current bar is a period of daily bars: today's live daily bar joins it.
PERIODS = ("1w", "1M")
#: The setting that gives a provider its source, named when a chart asks for it unset.
SETTINGS = {"temporaldb": "ARTS_CHARTS_TEMPORAL_URL"}
#: ponytail: past this many distinct questions every pacer is dropped at once (one refetch
#: each); an LRU if a deployment ever asks this many.
MAX_KEYS = 4096


@dataclass(frozen=True)
class Live:
    day: date              # the session's own date (New York for US equities, else UTC)
    partial: bool
    tape: Tape
    bars: list[dict]


def fold(minutes: list[dict], interval: str, segments: list[tuple[datetime, datetime]],
         since: datetime, day: date) -> list[dict]:
    """live-grid's 1m bars as `interval` bars: each minute in the segment `[a, b)` that holds
    it, bucketed from `a` (aware), so no bar crosses a segment edge; `1d` is one bar per
    segment, dated `day`. Bars starting before `since` are dropped (not fully covered, or
    before the seam). vwap is volume-weighted over the minutes that carry one."""
    width = None if interval == "1d" else interval_step(interval)
    bars: dict[datetime, dict] = {}
    for m in minutes:
        at = utc(m["date"])
        segment = next((a for a, b in segments if a <= at < b), None)
        if segment is None:
            continue
        start = segment if width is None else segment + ((at - segment) // width) * width
        if start < since:
            continue
        volume = float(m.get("volume") or 0.0)
        bar = bars.get(start)
        if bar is None:
            bar = bars[start] = {
                "date": day.isoformat() if width is None else start.isoformat(),
                "open": m["open"], "high": m["high"], "low": m["low"], "close": m["close"],
                "volume": 0.0, "vwap": None, "_pv": 0.0, "_v": 0.0}
        bar["high"], bar["low"] = max(bar["high"], m["high"]), min(bar["low"], m["low"])
        bar["close"], bar["volume"] = m["close"], bar["volume"] + volume
        if m.get("vwap") is not None and volume > 0:
            bar["_pv"] += m["vwap"] * volume
            bar["_v"] += volume
            bar["vwap"] = bar["_pv"] / bar["_v"]
    return [{k: v for k, v in bar.items() if not k.startswith("_")}
            for _, bar in sorted(bars.items())]


class ComposedBars:
    def __init__(self, history: dict[str, BarSource], live: LiveGridBars | None = None,
                 calendar: ExchangeCalendar | None = None,
                 now: Callable[[], datetime] | None = None,
                 extended: dict[str, BarSource] | None = None):
        self._history, self._live, self._calendar = history, live, calendar
        self._extended = extended or {}  # provider -> its source with pre and after hours
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sessions = UsEquitySessions(classify, calendar)
        self._pacers: dict[tuple, HistoryPacer] = {}
        self._memo: dict[tuple, tuple] = {}

    def check(self, provider: str, interval: str) -> None:
        """NotConfigured (a 422) for a provider with no history source here, naming the
        setting that configures it, and for an interval TemporalDB Gold cannot serve."""
        if provider not in self._history:
            hint = f"; set {SETTINGS[provider]}" if provider in SETTINGS else ""
            raise NotConfigured(f"provider {provider!r} is not configured on this server{hint}")
        if provider == "temporaldb" and interval not in TEMPORAL_INTERVALS:
            raise NotConfigured(DAILY_ONLY)

    async def _history_of(self, symbol, interval, start, end, provider, fresh, extended=False):
        key = (symbol, interval, start, end, provider, extended)
        pacer = self._pacers.get(key)
        if pacer is None:
            if len(self._pacers) >= MAX_KEYS:
                self._pacers.clear()
            source = (self._extended if extended else self._history)[provider]
            pacer = self._pacers[key] = HistoryPacer(
                lambda s, i, a, b, _p: source(s, i, a, b))
        if fresh:
            pacer.invalidate()
        return await pacer(symbol, interval, start, end, provider)

    async def _live_of(self, symbol, interval, start, end, session, now, fresh) -> Live | str:
        """Today's live bars, or why there are none (meta.live_reason)."""
        daily = interval == "1d" or interval in PERIODS  # today's bar is the regular session
        if not (is_intraday(interval) or daily):
            return "no_session"
        sessions = self._sessions
        day = now.astimezone(ZoneInfo(sessions.zone(symbol))).date()
        if not (start[:10] <= day.isoformat() <= end[:10]) or not sessions.is_open(symbol, day):
            return "no_session"
        if self._live is None:
            return "unavailable"
        covered = await self._live.covers(symbol)
        if not covered:
            return "unavailable" if covered is None else "not_covered"
        tz = timezone.utc
        extended = [t.astimezone(tz) for t in sessions.extended_open_close(symbol, day)]
        regular = [t.astimezone(tz) for t in sessions.open_close(symbol, day)]
        tape = await self._live.tape(symbol, extended[0], fresh)
        if tape is None:
            return "unavailable"
        if daily:
            segments = [tuple(regular)]
        else:  # pre-market, regular, after hours; one segment where they coincide (UTC day)
            edges = sorted({*extended, *regular})
            segments = list(zip(edges, edges[1:]))
        seam = regular[0] if daily or session == "regular" else extended[0]
        covered_from = tape.first or now  # nothing held: covered from now on
        partial = covered_from > seam
        # A bar starting before the span is not fully covered: dropped, a gap until the
        # first bar that is (series.seam_boundary in live-grid/app/series.py).
        bars = fold(tape.minutes, "1d" if daily else interval, segments,
                    max(seam, covered_from), day)
        return Live(day, partial, tape, bars)

    def _forming(self, symbol, interval, rows, now) -> str | None:
        if not rows:
            return None
        start = _naive_utc(rows[-1]["date"])
        try:
            ends = bar_end(symbol, interval, start, self._sessions)
        except ValueError:  # an interval bar_end cannot read: no claim either way
            return None
        return str(start) if ends > _naive_utc(now) else None

    async def __call__(self, symbol: str, interval: str, start: str, end: str, provider: str,
                       session: str = "extended", fresh: bool = False):
        self.check(provider, interval)
        now = self._now()
        if self._calendar:
            await self._calendar.load_around(XNYS, now)
        found = await self._live_of(symbol, interval, start, end, session, now, fresh)
        live = found if isinstance(found, Live) else None
        reason = None if live else found
        history_end = end
        if live is not None:  # partial too: a gap, never an ODP call for the session (L9)
            history_end = (live.day - timedelta(days=1)).isoformat()
        extended = (session != "regular" and is_intraday(interval)
                    and provider in self._extended)
        history = (await self._history_of(symbol, interval, start, history_end, provider, fresh,
                                          extended)
                   if start[:10] <= history_end[:10] else NO_HISTORY)
        rows, meta = history
        days = NO_HISTORY
        if live is not None and interval in PERIODS:
            first = (live.day - timedelta(days=live.day.weekday()) if interval == "1w"
                     else live.day.replace(day=1)).isoformat()
            since = max(start[:10], first)
            if since <= history_end[:10]:  # the period's days to yesterday, never today (L9)
                days = await self._history_of(symbol, "1d", since, history_end, provider, fresh)
            rows = ([r for r in rows if str(r["date"])[:10] < first]
                    + resample(days[0] + live.bars, interval))
        elif live is not None:
            rows = rows + live.bars
        forming = self._forming(symbol, interval, rows, now)
        key = (symbol, interval, start, end, provider, session)
        tape, partial = (live.tape, live.partial) if live else (None, None)
        held = self._memo.get(key)
        if (held is not None and held[0] is history and held[1] is days and held[2] is tape
                and held[3:6] == (partial, forming, reason)):
            return held[6]
        state = False if live is None else ("partial" if live.partial else True)
        answer = (rows, {**meta, "live": state, "live_reason": reason,
                         "live_volume": None if live is None else "venue", "forming": forming})
        if len(self._memo) >= MAX_KEYS:
            self._memo.clear()
        self._memo[key] = (history, days, tape, partial, forming, reason, answer)
        return answer
