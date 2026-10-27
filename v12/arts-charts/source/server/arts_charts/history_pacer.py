# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""One study websocket's history fetch, paced to the bar.

The study sockets (/ta_chart_ws, /ta_series_ws) rebuild their series on every
push -- TA_PUSH_INTERVAL_MS, 1 s by default. build_series is two very
different costs: the tick tail (kdb, local) and the history (an HTTP round
trip to the OpenBB API, which for provider=eodhd is a billed EODHD call on
every push). On 2026-09-30 a thirty-card board at 1 s spent the whole
100,000-a-day EODHD key in under two hours and kept asking at the same rate
after every answer was a 402.

So a socket gets one of these as build_series' `history`: it answers from the
last history until a bar's worth of time has passed (capped at 15 minutes for
daily and longer bars, whose history does not move intraday anyway), and
after a failure it re-raises that failure without asking again until a
backoff has passed -- 1 minute, doubling, capped at 15. The tick tail is
untouched and still refreshes every push.
"""
from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

#: The longest a socket reuses one history answer, whatever the bar width.
MAX_REUSE_S = 900.0
#: First retry delay after a failed history fetch; doubles per failure.
BACKOFF_S = 60.0
#: The longest a socket waits between retries of a failing history fetch.
MAX_BACKOFF_S = 900.0

_STEPS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


def interval_step(interval: str) -> timedelta:
    """One bar width for an OpenBB interval string ('1d', '5m', '1h').

    Copied from openbb-docker kdb-store/kdb_store/ranges.py @ c83446c0, the
    package's only use of kdb-store.
    """
    m = re.fullmatch(r"(\d*)\s*([a-zA-Z]+)", str(interval).strip())
    if not m:
        raise ValueError(f"Could not parse interval {interval!r}.")
    n = int(m.group(1) or 1)
    if m.group(2) == "M":  # a month, as ta/session reads it: `1m` is a minute, `1M` a month
        return timedelta(days=30 * n)
    unit = m.group(2).lower()
    if unit in ("mo", "mon", "month", "months"):
        return timedelta(days=30 * n)
    base = _STEPS.get(unit[0])
    if base is None:
        raise ValueError(f"Unsupported interval {interval!r}.")
    return base * n


Fetch = Callable[[str, str, str, str, str], Awaitable[tuple[list[dict], dict]]]


def reuse_seconds(interval: str) -> float:
    """How long one history answer stands: one bar, at most MAX_REUSE_S."""
    try:
        bar = interval_step(interval).total_seconds()
    except ValueError:
        return MAX_REUSE_S
    return min(max(bar, 1.0), MAX_REUSE_S)


class HistoryPacer:
    """A drop-in for fetch_series, scoped to one socket."""

    def __init__(self, fetch: Fetch, clock: Callable[[], float] = time.monotonic,
                 reuse: Callable[[str], float] | None = None):
        self._fetch = fetch
        self._clock = clock
        self._reuse = reuse  # None: the module's reuse_seconds, looked up per call
        self._key: tuple | None = None
        self._answer: tuple[list[dict], dict] | None = None
        self._fresh_until = 0.0
        self._failures = 0
        self._retry_at = 0.0
        self._error: Exception | None = None

    def invalidate(self) -> None:
        """Forget the stored answer and failure: the next call fetches. For a caller that
        must not judge a bar on a read made before it ended (the worker)."""
        self._fresh_until, self._error, self._failures = 0.0, None, 0

    def refresh(self) -> None:
        """`invalidate`, except while a failure is held: its backoff and one-time log stand."""
        if self._error is None:
            self.invalidate()

    async def __call__(self, symbol: str, interval: str, start: str, end: str,
                       provider: str = "kdb") -> tuple[list[dict], dict]:
        key = (symbol, interval, start, end, provider)
        now = self._clock()
        if key != self._key:
            # A different question (the window moved, the symbol changed):
            # nothing stored answers it, and a stored failure was about
            # something else.
            self._key, self._answer, self._failures, self._error = key, None, 0, None
        elif self._error is not None and now < self._retry_at:
            raise self._error
        elif self._answer is not None and now < self._fresh_until:
            return self._answer
        try:
            answer = await self._fetch(symbol, interval, start, end, provider)
        except Exception as exc:
            self._failures += 1
            self._error = exc
            self._retry_at = now + min(BACKOFF_S * 2 ** (self._failures - 1), MAX_BACKOFF_S)
            raise
        self._failures, self._error = 0, None
        self._answer = answer
        self._fresh_until = now + (self._reuse or reuse_seconds)(interval)
        return answer
