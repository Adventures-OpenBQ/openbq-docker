# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Exchange holidays and early closes, from openbq-docker's `GET /api/v1/calendar/trading`.

`ExchangeCalendar.load(mic, year)` fetches a year once and keeps it; every
lookup after that is synchronous and does no I/O (`get`). `UsEquitySessions`
reads US-equity sessions from the loaded XNYS year and behaves as a plain
Monday-Friday 09:30-16:00 calendar for a year that is not loaded, so a missing
or unreachable route degrades to the old behaviour rather than failing a chart.

A good answer and a 404 ("no calendar": unknown MIC, year out of range) are
kept 24 hours. A network error, a 5xx or an unreadable body is an outage: the
year stays as it was (the last good answer, else none) and is asked again after
5 minutes. Neither the URL nor the credentials reach a log line or an error.
"""
from __future__ import annotations

import asyncio
import logging
import time as clock_time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("arts-charts.calendar")

PATH = "/api/v1/calendar/trading"
KEEP = 24 * 3600.0
RETRY = 5 * 60.0
TIMEOUT = 5.0  # a hung route must not hold a chart request or a worker pass for long
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
XNYS = "XNYS"


@dataclass(frozen=True)
class Year:
    working: frozenset[int]                          # weekday numbers that can be sessions
    holidays: dict[date, tuple[bool, time | None]]   # day -> (is_early_close, close); Official = (False, None)


def _parse(body: dict) -> Year:
    data = body["data"]
    working = frozenset(_DAYS.index(d.strip()) for d in data["TradingHours"]["WorkingDays"].split(","))
    holidays = {}
    for day, entry in data["ExchangeHolidays"].items():
        if entry["Type"] == "EarlyClose":
            holidays[date.fromisoformat(day)] = (True, time.fromisoformat(entry["EarlyClose"]))
        elif entry["Type"] == "Official":
            holidays[date.fromisoformat(day)] = (False, None)
    return Year(working, holidays)


class ExchangeCalendar:
    def __init__(self, base_url: str, auth: tuple[str, str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = clock_time.monotonic):
        self._url = base_url.rstrip("/") + PATH
        self._auth, self._transport, self._clock = auth, transport, clock
        #: (mic, year) -> (Year or None, when to ask again)
        self._cache: dict[tuple[str, int], tuple[Year | None, float]] = {}
        self._inflight: dict[tuple[str, int], asyncio.Task] = {}

    def get(self, mic: str, year: int) -> Year | None:
        """The loaded year, or None (not loaded, no calendar, or unreachable). Never does I/O."""
        entry = self._cache.get((mic, year))
        return entry[0] if entry else None

    async def load(self, mic: str, year: int) -> None:
        """Fetch (mic, year) unless it is still fresh. Never raises for an outage; callers
        that arrive while a fetch is out share it."""
        key = (mic, year)
        entry = self._cache.get(key)
        if entry and entry[1] > self._clock():
            return
        task = self._inflight.get(key)
        if task is None:
            task = self._inflight[key] = asyncio.ensure_future(self._fetch(key))
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        await asyncio.shield(task)

    async def _fetch(self, key: tuple[str, int]) -> None:
        mic, year = key
        now = self._clock()
        entry = self._cache.get(key)
        previous = entry[0] if entry else None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, auth=self._auth,
                                         transport=self._transport) as client:
                response = await client.get(self._url, params={"exchange": mic, "year": year})
            if response.status_code == 404:
                self._cache[key] = (None, now + KEEP)
                return
            response.raise_for_status()
            self._cache[key] = (_parse(response.json()), now + KEEP)
        except Exception as exc:  # noqa: BLE001 - any failure is an outage, never a chart failure
            # The class name only: an httpx message can carry the URL.
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            log.warning("calendar %s %s unavailable (%s%s); retrying in 5 minutes", mic, year,
                        type(exc).__name__, f" {status}" if status else "")
            self._cache[key] = (previous, now + RETRY)

    async def load_around(self, mic: str, now: datetime) -> None:
        """The years either side of `now`: what an offset, a look-back or a bar can reach.

        ponytail: a `T-Nbd` reaching back more than a year crosses into a year that is not
        loaded and counts every weekday there; widen the span if one is ever asked for.
        """
        year = now.astimezone(timezone.utc).year
        await asyncio.gather(*(self.load(mic, y) for y in (year - 1, year, year + 1)))


class UtcSessions:
    """Crypto and forex: every day is a session from 00:00 to 24:00 UTC.

    Extended is the same window -- there is no narrower "regular" session to
    be wider than, so `@SOD`/`@EOD` read the same UTC day under either
    `session` choice.
    """
    def zone(self, symbol): return "UTC"
    def is_open(self, symbol, day): return True
    def open_close(self, symbol, day):
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return start, start + timedelta(days=1)
    def extended_open_close(self, symbol, day):
        return self.open_close(symbol, day)


class UsEquitySessions:
    """XNYS sessions for US equities from the loaded calendar; the UTC day for the rest.

    Where the year is not loaded: every weekday is a session, 09:30-16:00.
    Extended hours are 04:00-20:00; on an early-close day they end 4 hours after
    the early close (13:00 -> 17:00), the venues' own early-day rule. The route
    carries no pre-market or after-hours times to read instead.
    """

    _ZONE = "America/New_York"

    def __init__(self, classify: Callable[[str], str], calendar: ExchangeCalendar | None = None):
        self._classify, self._calendar = classify, calendar
        self._utc = UtcSessions()

    def _equity(self, symbol: str) -> bool:
        return self._classify(symbol) == "us"

    def _year(self, day: date) -> Year | None:
        return self._calendar.get(XNYS, day.year) if self._calendar else None

    def zone(self, symbol):
        return self._ZONE if self._equity(symbol) else "UTC"

    def is_open(self, symbol, day):
        if not self._equity(symbol):
            return True
        year = self._year(day)
        if year is None:
            return day.weekday() < 5
        held = year.holidays.get(day)
        return day.weekday() in year.working and not (held and not held[0])

    def _close(self, day: date) -> time:
        year = self._year(day)
        held = year.holidays.get(day) if year else None
        return held[1] if held and held[0] else time(16, 0)

    def _bounds(self, day, start: time, end: time):
        zone = ZoneInfo(self._ZONE)
        return datetime.combine(day, start, tzinfo=zone), datetime.combine(day, end, tzinfo=zone)

    def open_close(self, symbol, day):
        if not self._equity(symbol):
            return self._utc.open_close(symbol, day)
        return self._bounds(day, time(9, 30), self._close(day))

    def extended_open_close(self, symbol, day):
        if not self._equity(symbol):
            return self._utc.extended_open_close(symbol, day)
        end = min(time(20, 0), (datetime.combine(day, self._close(day)) + timedelta(hours=4)).time())
        return self._bounds(day, time(4, 0), end)
