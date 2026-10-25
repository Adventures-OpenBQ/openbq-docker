# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""GET /api/v1/calendar/trading?exchange=<MIC>&year=<YYYY>: one exchange-year in EODHD v2 shape.

The body is what BDOBB's normalizeCalendar reads: {"data": {Timezone,
TradingHours, ExchangeHolidays}}. A weekday that is not a session is an
Official closure; a session closing before the year's regular close is an
EarlyClose with that local time. A calendar whose regular close changed during
the year (XTKS 2024-11-05) reports the year-end close, and each session is
compared with the regular close in effect on its own date. 404 means "no calendar" to the client: an
unknown MIC, or a year outside 1990-2040 or the calendar's own bounds.
"""
import asyncio
from openbb_core.app.router import Router
from starlette.responses import JSONResponse
from openbq_calendar.legacy import build
from .calendar_v1 import register
router = Router(prefix="")
register(router)


@router.command(methods=["GET"], no_validate=True, widget_config={"exclude": True})
async def trading(exchange: str, year: int):
    """Trading calendar for one exchange (ISO MIC) and year, EODHD v2 shape."""
    body = await asyncio.to_thread(build, exchange.upper(), year)
    if body is None:
        return JSONResponse({"detail": f"No trading calendar for {exchange} {year}."}, status_code=404)
    return JSONResponse(body)
