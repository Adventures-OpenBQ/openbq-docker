# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The current session's minute bars from live-grid's kdb tick plane.

Two calls, both under live-grid's Basic-auth middleware with the stack's pair:

- `GET /api/subscriptions` -> `{pinned, leased, ...}`: the symbols live-grid
  holds at the vendor. Their union is what is covered, kept 60 s (a failure
  is "nothing covered", kept as long).
- `GET /ticks?symbol=&interval=1m&start=` -> `{symbol, interval, bars, span}`:
  the merged route of the live-composed-bars spec §4, kdb + lake only. Always
  `1m`, from the session's extended open: ComposedBars folds the minutes into
  the chart's interval, anchored at the session open, so one call per symbol
  serves every interval. Paced by HistoryPacer: reused 5 s (shorter than one
  1m bar), and after a failure (unreachable, 401, a 404 from a live-grid
  without the route) not asked again until its backoff passes -- 1 minute,
  doubling, capped at 15.

live-grid's `/series` is never called: it fetches EODHD history first.
Neither the URL nor the credentials reach a log line.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from arts_charts.history_pacer import HistoryPacer

log = logging.getLogger("arts-charts.live-grid")

COVERAGE_S = 60.0
#: The longest a tape answer is reused: shorter than one 1m bar.
LIVE_REUSE_S = 5.0
TIMEOUT = 5.0  # a hung live-grid must not hold a chart for long: history serves alone


def utc(raw) -> datetime:
    """An ISO stamp as an aware UTC datetime; a naive one is UTC (the tick plane's clock)."""
    at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)


@dataclass(frozen=True)
class Tape:
    minutes: list[dict]          # live-grid's 1m bars, oldest first
    first: datetime | None       # span.first: the oldest tick held, or None (none held)


def _brief(exc: BaseException) -> str:
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    return type(exc).__name__ + (f" {status}" if status else "")


class LiveGridBars:
    def __init__(self, base_url: str, auth: httpx.Auth | tuple[str, str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._base = base_url.rstrip("/")
        self._auth, self._transport, self._clock = auth, transport, clock
        self._covered: frozenset[str] = frozenset()
        self._covered_until = float("-inf")
        # ponytail: one pacer per symbol, never evicted -- bounded by the symbols charts ask for.
        self._pacers: dict[str, HistoryPacer] = {}
        self._logged: dict[str, BaseException] = {}  # a held failure is logged once, not per call

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, auth=self._auth,
                                     transport=self._transport) as client:
            response = await client.get(self._base + path, params=params)
            response.raise_for_status()
            return response.json()

    async def covers(self, symbol: str) -> bool:
        if self._clock() >= self._covered_until:
            try:
                payload = await self._get("/api/subscriptions")
                self._covered = frozenset(str(s).strip().upper() for s in
                                          [*payload["pinned"], *payload["leased"]])
            except Exception as exc:  # noqa: BLE001 - live-grid down: nothing is covered
                log.warning("live-grid subscriptions unavailable (%s)", _brief(exc))
                self._covered = frozenset()
            self._covered_until = self._clock() + COVERAGE_S
        return symbol.strip().upper() in self._covered

    async def _tape(self, symbol, interval, start, _end, _provider) -> Tape:
        payload = await self._get("/ticks", {"symbol": symbol, "interval": interval,
                                             "start": start})
        span = payload["span"]
        bars = list(payload["bars"])
        for bar in bars:  # one bad bar fails the whole tape: the pacer holds it, history serves alone
            utc(bar["date"])
            for key in ("open", "high", "low", "close"):
                if isinstance(bar[key], bool) or not isinstance(bar[key], (int, float)):
                    raise ValueError(f"bar {key} is not a number")
        return Tape(bars, utc(span["first"]) if span else None)

    async def tape(self, symbol: str, start: datetime, fresh: bool = False) -> Tape | None:
        """The minutes from `start` (aware) and the span's first tick; None when live-grid
        cannot answer now (history serves alone)."""
        pacer = self._pacers.setdefault(symbol, HistoryPacer(
            self._tape, self._clock, reuse=lambda _interval: LIVE_REUSE_S))
        if fresh:
            pacer.refresh()
        try:
            return await pacer(symbol, "1m", start.astimezone(timezone.utc).isoformat(), "",
                               "live-grid")
        except Exception as exc:  # noqa: BLE001 - the pacer holds the failure until its backoff
            if self._logged.get(symbol) is not exc:
                self._logged[symbol] = exc
                log.warning("live-grid ticks unavailable for %s (%s)", symbol, _brief(exc))
            return None
