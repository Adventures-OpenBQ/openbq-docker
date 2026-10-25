# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
from functools import lru_cache
import exchange_calendars as xc
import pandas as pd

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hhmmss(series, tz):
    return series.dt.tz_convert(tz).dt.strftime("%H:%M:%S")


@lru_cache(maxsize=512)  # the 512 most recent exchange-years (71 calendars x 51 years would be 3,621)
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
    regimes = [(since, t.strftime("%H:%M:%S")) for since, t in cal.close_times]  # local, oldest first

    def regular_close(day):
        return [t for since, t in regimes if since is None or since <= day][-1]

    start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31")
    hours = {
        "Open": opens.mode()[0],
        "Close": regular_close(end),
        "WorkingDays": ", ".join(d for d, on in zip(DAYS, cal.weekmask) if on == "1"),
    }
    breaks = cal.break_starts.dropna()
    if len(breaks):
        hours["LunchBreakStart"] = _hhmmss(breaks, tz).mode()[0]
        hours["LunchBreakEnd"] = _hhmmss(cal.break_ends.dropna(), tz).mode()[0]

    named = {}
    if cal.regular_holidays is not None:
        named = cal.regular_holidays.holidays(start, end, return_name=True).to_dict()
    weekdays = pd.bdate_range(start, end, freq="C", weekmask=cal.weekmask)
    holidays = {
        d.strftime("%Y-%m-%d"): {"Holiday": named.get(d, "Market closed"), "Type": "Official"}
        for d in weekdays.difference(cal.sessions)
    }
    for session, close in closes.items():
        if close < regular_close(session):
            holidays[session.strftime("%Y-%m-%d")] = {
                "Holiday": "Early close",
                "Type": "EarlyClose",
                "EarlyClose": close,
            }
    return {
        "data": {
            "Name": mic,
            "Code": mic,
            "OperatingMIC": mic,
            "Timezone": tz,
            "TradingHours": hours,
            "ExchangeHolidays": dict(sorted(holidays.items())),
        }
    }
