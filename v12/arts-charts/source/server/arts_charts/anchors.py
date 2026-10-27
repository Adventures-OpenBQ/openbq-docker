# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Anchor expressions, resolved on the server.

The grammar is the client's `dateExpressions` atom (bdobb-v2), ported: a
named anchor, signed offsets, an optional `@` time. Plus one atom the client
cannot resolve because it is a fact about the data: `OBS-n`, the n-th most
recent trade. Clock and session forms resolve in the SYMBOL'S exchange zone,
not the viewer's; the payload echoes the instant actually used.

`@SOD`/`@EOD` (v12.4.0) are the day's bounds under the caller's `session`
choice, not aliases of `@open`/`@close`: `session="regular"` is the same
open/close, `session="extended"` (the default) is the wider pre/after-hours
window. They accept and ignore an optional four-character venue suffix
(`@SOD(XNYS)`) since XNYS is the only equity calendar this server knows.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger("live-grid.anchors")

_NAMED = re.compile(r"^(now|trade_date|prev_trade_date|session_open|session_close|T)")
_OBS = re.compile(r"^OBS-(\d{1,7})$")
_OFFSET = re.compile(r"([+-])(\d{1,6})(min|bd|s|h|d)?")
_AT = re.compile(
    r"@(?:(\d{2}):(\d{2})|(open)|(close)|(SOD)(?:\(([A-Z0-9]{4})\))?|(EOD)(?:\(([A-Z0-9]{4})\))?)$"
)


@dataclass(frozen=True)
class Atom:
    anchor: str
    n: int | None
    offsets: tuple[tuple[int, int, str], ...]
    at: tuple | None  # ("clock", h, m) | ("open",) | ("close",) | ("sod",) | ("eod",)


def parse_anchor(text: str) -> Atom | None:
    text = (text or "").strip()
    if not text:
        return None
    m = _OBS.match(text)
    if m:
        n = int(m.group(1))
        return Atom("OBS", n, (), None) if n > 0 else None
    at = None
    suffix = _AT.search(text)
    if suffix:
        # Groups 6/8 are the optional venue suffix (`SOD(XNYS)`); accepted
        # and ignored -- XNYS is the only equity calendar this server has.
        if suffix.group(5):
            at = ("sod",)
        elif suffix.group(7):
            at = ("eod",)
        elif suffix.group(3):
            at = ("open",)
        elif suffix.group(4):
            at = ("close",)
        else:
            h, mi = int(suffix.group(1)), int(suffix.group(2))
            if h > 23 or mi > 59:
                return None
            at = ("clock", h, mi)
        text = text[: suffix.start()]
    named = _NAMED.match(text)
    if not named:
        return None
    pos = named.end()
    offsets: list[tuple[int, int, str]] = []
    while pos < len(text):
        m = _OFFSET.match(text, pos)
        if not m:
            return None
        offsets.append((-1 if m.group(1) == "-" else 1, int(m.group(2)), m.group(3) or "d"))
        pos = m.end()
    return Atom(named.group(1), None, tuple(offsets), at)


def _iso(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def is_anchor(text: str) -> bool:
    return _iso(text or "") is not None or parse_anchor(text) is not None


class Sessions(Protocol):
    def zone(self, symbol: str) -> str: ...
    def is_open(self, symbol: str, day: date) -> bool: ...
    def open_close(self, symbol: str, day: date) -> tuple[datetime, datetime]: ...
    def extended_open_close(self, symbol: str, day: date) -> tuple[datetime, datetime]: ...


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


def _next_open(sessions: Sessions, symbol: str, day: date) -> date:
    while not sessions.is_open(symbol, day):
        day += timedelta(days=1)
    return day


def _prev_open(sessions: Sessions, symbol: str, day: date) -> date:
    while not sessions.is_open(symbol, day):
        day -= timedelta(days=1)
    return day


def _add_bd(sessions: Sessions, symbol: str, at: datetime, n: int) -> datetime:
    step = 1 if n > 0 else -1
    day = at.date()
    for _ in range(abs(n)):
        day += timedelta(days=step)
        day = _next_open(sessions, symbol, day) if step > 0 else _prev_open(sessions, symbol, day)
    return at.replace(year=day.year, month=day.month, day=day.day)


async def resolve_anchor(text: str, symbol: str, now: datetime, sessions: Sessions,
                         obs: Callable[[str, int], Awaitable[datetime | None]],
                         session: str = "extended") -> datetime | None:
    """Naive UTC instant for `text`, or None when it does not resolve.

    `session` only matters to `@SOD`/`@EOD`: `"regular"` resolves through
    `sessions.open_close` (the same as `@open`/`@close`), anything else
    through `sessions.extended_open_close`. Every other atom is unaffected --
    unlike the client, this resolver never refuses for a missing session; the
    default is the wider window.
    """
    literal = _iso(text or "")
    if literal is not None:
        return literal
    atom = parse_anchor(text)
    if atom is None:
        return None
    if atom.anchor == "OBS":
        return await obs(symbol, atom.n or 0)
    zone = ZoneInfo(sessions.zone(symbol))
    now_z = now.replace(tzinfo=timezone.utc).astimezone(zone)
    today = now_z.date()
    if atom.anchor == "now":
        at = now_z
    elif atom.anchor == "T":
        at = now_z.replace(hour=0, minute=0, second=0, microsecond=0)
    elif atom.anchor == "trade_date":
        at = sessions.open_close(symbol, _prev_open(sessions, symbol, today))[1]
    elif atom.anchor == "prev_trade_date":
        at = sessions.open_close(symbol, _prev_open(sessions, symbol, _prev_open(sessions, symbol, today) - timedelta(days=1)))[1]
    elif atom.anchor == "session_open":
        at = sessions.open_close(symbol, _next_open(sessions, symbol, today))[0]
    else:  # session_close
        at = sessions.open_close(symbol, _next_open(sessions, symbol, today))[1]
    for sign, amount, unit in atom.offsets:
        if unit == "bd":
            at = _add_bd(sessions, symbol, at, sign * amount)
        else:
            # Exact offsets are elapsed time, not wall-clock: do the arithmetic
            # in UTC so a DST transition inside the window doesn't shift the
            # result by an hour, then convert back to the exchange zone for
            # any `@`/`bd` step still to come.
            seconds = {"s": 1, "min": 60, "h": 3600, "d": 86400}[unit] * amount
            at = (at.astimezone(timezone.utc) + timedelta(seconds=sign * seconds)).astimezone(zone)
    if atom.at is not None:
        rolls_forward = atom.at[0] in ("open", "close", "sod", "eod")
        day = _next_open(sessions, symbol, at.date()) if rolls_forward else at.date()
        if atom.at[0] == "open":
            at = sessions.open_close(symbol, day)[0]
        elif atom.at[0] == "close":
            at = sessions.open_close(symbol, day)[1]
        elif atom.at[0] == "sod":
            bounds = sessions.open_close if session == "regular" else sessions.extended_open_close
            at = bounds(symbol, day)[0]
        elif atom.at[0] == "eod":
            bounds = sessions.open_close if session == "regular" else sessions.extended_open_close
            at = bounds(symbol, day)[1]
        else:
            at = at.replace(hour=atom.at[1], minute=atom.at[2], second=0, microsecond=0)
    return at.astimezone(timezone.utc).replace(tzinfo=None)

