# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB),
# Copyright (c) 2021-2026 OpenBB Inc., licensed under the Apache License, Version 2.0.
# Modifications Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""TMX Router."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from openbb_core.app.router import Router

from openbb_tmx import CHARTING_INSTALLED
from openbb_tmx.routers.calendar import router as calendar_router
from openbb_tmx.routers.currency import router as currency_router
from openbb_tmx.routers.derivatives import router as derivatives_router
from openbb_tmx.routers.equity import router as equity_router
from openbb_tmx.routers.estimates import router as estimates_router
from openbb_tmx.routers.etf import router as etf_router
from openbb_tmx.routers.fixedincome import router as fixedincome_router
from openbb_tmx.routers.fundamentals import router as fundamentals_router
from openbb_tmx.routers.index import router as index_router
from openbb_tmx.routers.markets import router as markets_router
from openbb_tmx.routers.news import router as news_router
from openbb_tmx.routers.ownership import router as ownership_router
from openbb_tmx.routers.udf import router as udf_router

router = Router(prefix="", description="TMX provider router.")

for _subrouter in (
    equity_router,
    fundamentals_router,
    calendar_router,
    ownership_router,
    estimates_router,
    etf_router,
    index_router,
    derivatives_router,
    currency_router,
    fixedincome_router,
    markets_router,
    news_router,
    udf_router,
):
    router.include_router(_subrouter)


@asynccontextmanager
async def _lifespan(_):
    """Close the pooled TMX sessions when the API stops."""
    from openbb_tmx.utils.session import close_sessions

    try:
        yield
    finally:
        await close_sessions()


router.api_router.lifespan_context = _lifespan

_APPS_JSON = Path(__file__).parent / "assets" / "apps.json"


@router.api_router.get("/apps.json", include_in_schema=False)
async def tmx_apps() -> list:
    """Serve the bundled TMX dashboard template."""
    apps = json.loads(_APPS_JSON.read_text(encoding="utf-8"))
    hidden = {"tmx_equity_screener_builder_obb"}  # needs pywry, not installed
    if not CHARTING_INSTALLED:
        hidden |= {
            f"tmx_derivatives_options_{name}_custom_obb"
            for name in ("term_structure", "stats", "smile", "surface")
        }
    for app in apps:
        for tab in app.get("tabs", {}).values():
            tab["layout"] = [
                widget
                for widget in tab.get("layout", [])
                if widget.get("i") not in hidden
            ]
        app["tabs"] = {
            name: tab for name, tab in app.get("tabs", {}).items() if tab["layout"]
        }
        for group in app.get("groups", []):
            if "widgetIds" in group:
                group["widgetIds"] = [
                    wid for wid in group["widgetIds"] if wid not in hidden
                ]
    return apps
