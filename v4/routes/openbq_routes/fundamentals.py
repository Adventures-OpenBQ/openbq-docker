# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""GET /api/v1/fundamentals/fiscal_year_end?symbol=<TICKER> -> {"fiscalYearEnd": "September"}.

Read from Yahoo's lastFiscalYearEnd through the vendored openbq_yfinance
client. A symbol Yahoo has no year end for answers 404, which BDOBB treats as
"unavailable": it warns and falls back.
"""
from datetime import datetime, timedelta, timezone

from openbb_core.app.router import Router
from openbq_yfinance.client import call, ticker
from starlette.responses import JSONResponse

router = Router(prefix="")


def month_of(timestamp: int) -> str:
    """The fiscal year-end month of a year-end date.

    A 52/53-week year ending on the weekday nearest a month end can land up to
    three days into the next month (Home Depot: 2026-02-01 for January), so
    the first three days count as the month before.
    """
    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
    if day.day <= 3:
        day -= timedelta(days=day.day)
    return day.strftime("%B")


@router.command(methods=["GET"], no_validate=True, widget_config={"exclude": True})
async def fiscal_year_end(symbol: str):
    """Fiscal year-end month for one ticker, as a month name."""
    info = await call(lambda: ticker(symbol).info)
    timestamp = (info or {}).get("lastFiscalYearEnd")
    if not isinstance(timestamp, (int, float)):
        return JSONResponse({"detail": f"No fiscal year end for {symbol}."}, status_code=404)
    return JSONResponse({"fiscalYearEnd": month_of(int(timestamp))})
