# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""GET /api/v1/calendar/trading?exchange=<MIC>&year=<YYYY>: one exchange-year in EODHD v2 shape.

The body is what BDOBB's normalizeCalendar reads: {"data": {Timezone,
TradingHours, ExchangeHolidays}}. A weekday that is not a session is an
Official closure; a session closing before the year's regular close is an
EarlyClose with that local time. 404 means "no calendar" to the client: an
unknown MIC, or a year outside 1990-2040 or the calendar's own bounds.
"""
import asyncio
from functools import lru_cache

import exchange_calendars as xc
import pandas as pd
from openbb_core.app.router import Router
from starlette.responses import JSONResponse

router = Router(prefix="")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hhmmss(series: pd.Series, tz: str) -> pd.Series:
    return series.dt.tz_convert(tz).dt.strftime("%H:%M:%S")


@lru_cache(maxsize=256)
def build(mic: str, year: int) -> dict | None:
    """The EODHD v2 envelope for one exchange-year, or None when there is none."""
    if mic not in xc.get_calendar_names() or not 1990 <= year <= 2040:
        return None
    try:
        cal = xc.get_calendar(mic, start=f"{year}-01-01", end=f"{year}-12-31")
    except ValueError:  # the year is outside this calendar's bounds
        return None
    tz = str(cal.tz)
    opens, closes = _hhmmss(cal.opens, tz), _hhmmss(cal.closes, tz)
    hours = {
        "Open": opens.mode()[0],
        "Close": closes.mode()[0],
        "WorkingDays": ", ".join(d for d, on in zip(DAYS, cal.weekmask) if on == "1"),
    }
    breaks = cal.break_starts.dropna()
    if len(breaks):
        hours["LunchBreakStart"] = _hhmmss(breaks, tz).mode()[0]
        hours["LunchBreakEnd"] = _hhmmss(cal.break_ends.dropna(), tz).mode()[0]

    start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31")
    named = {}
    if cal.regular_holidays is not None:
        named = cal.regular_holidays.holidays(start, end, return_name=True).to_dict()
    weekdays = pd.bdate_range(start, end, freq="C", weekmask=cal.weekmask)
    holidays = {
        d.strftime("%Y-%m-%d"): {"Holiday": named.get(d, "Market closed"), "Type": "Official"}
        for d in weekdays.difference(cal.sessions)
    }
    for session, close in closes[closes < hours["Close"]].items():
        holidays[session.strftime("%Y-%m-%d")] = {"Holiday": "Early close", "Type": "EarlyClose", "EarlyClose": close}
    return {"data": {
        "Name": mic, "Code": mic, "OperatingMIC": mic, "Timezone": tz,
        "TradingHours": hours, "ExchangeHolidays": dict(sorted(holidays.items())),
    }}


@router.command(methods=["GET"], no_validate=True, widget_config={"exclude": True})
async def trading(exchange: str, year: int):
    """Trading calendar for one exchange (ISO MIC) and year, EODHD v2 shape."""
    body = await asyncio.to_thread(build, exchange.upper(), year)
    if body is None:
        return JSONResponse({"detail": f"No trading calendar for {exchange} {year}."}, status_code=404)
    return JSONResponse(body)
