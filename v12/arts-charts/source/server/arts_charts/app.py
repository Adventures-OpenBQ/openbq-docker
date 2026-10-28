# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The arts-charts service: `uvicorn --factory arts_charts.app:create_app`.

Settings, all from the environment:
  ARTS_CHARTS_DB            sqlite:///<path> (default sqlite:///arts-charts.db) or postgresql://...
  ARTS_CHARTS_ODP_URL       openbq-docker's ODP REST API base URL (required)
  ARTS_CHARTS_ODP_USER      with ARTS_CHARTS_ODP_PASSWORD: that API's Basic credentials; unset, the
                            stack's OPENBB_API_USERNAME / OPENBB_API_PASSWORD
  ARTS_CHARTS_DEFAULT_PROVIDER
                            the history provider of a chart that names none: yfinance (default),
                            eodhd, or temporaldb when ARTS_CHARTS_TEMPORAL_URL is set
  ARTS_CHARTS_TEMPORAL_URL  TemporalDB's API base URL (e.g. http://temporaldb-api:8080); unset,
                            a temporaldb chart is a 422 naming this setting
  ARTS_CHARTS_TEMPORAL_TOKEN
                            with the URL (required then): a bearer token from TemporalDB's scope
                            policy (TEMPORALDB_SCOPE_POLICY), whose principal saves and runs
                            arts-charts' one Gold query
  ARTS_CHARTS_TEMPORAL_DATASET
                            the Gold daily dataset: eodhd.eod (default) or
                            yfinance.YfinanceEquityHistorical
  ARTS_CHARTS_LIVE_GRID_URL live-grid's base URL (e.g. http://live-grid:6903), called with the
                            stack's pair; unset, no chart is live (history alone, meta.live false)
  OPENBB_API_AUTH, OPENBB_API_USERNAME, OPENBB_API_PASSWORD
                            the stack's pair: when OPENBB_API_AUTH is truthy every route demands
                            it (except an ntfy button, which carries its own signed token)
  ARTS_CHARTS_RENDER_DIR    the built snapshot page (default: client/render/dist in a checkout)
  ARTS_CHARTS_SECRET        signs and checks wake, button and worker tokens; unset, every
                            wake, button and worker write is refused

Snapshots also need the `snapshots` extra and its Chromium:
`playwright install --only-shell chromium`. Without them every other route
works and a snapshot answers 503 saying what is missing.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from starlette.middleware import Middleware
from mcp.server.transport_security import TransportSecuritySettings

from arts_charts.auth import BasicAuthMiddleware, StackAuth, odp_credentials
from arts_charts.calendar import ExchangeCalendar
from arts_charts.chart_tools import chart_mcp
from arts_charts.companions import companions_router
from arts_charts.composed import ComposedBars
from arts_charts.documents import Feed, documents_router
from arts_charts.inbox import inbox_router
from arts_charts.live_grid import LiveGridBars
from arts_charts.odp_bars import OdpBars
from arts_charts.router import BarSource, default_provider, router
from arts_charts.schedules import schedules_router
from arts_charts.snapshots import DEFAULT_RENDER_DIR, Snapshots, kept_snapshot_router, snapshot_router
from arts_charts.store import DEFAULT_URL, Store
from arts_charts.temporal_gold import DEFAULT_DATASET, TemporalGoldBars
from arts_charts.watches import watches_router

#: Where Rita's chart tools are served (Streamable HTTP).
MCP_PATH = "/charts/mcp"


def create_app(bars: BarSource | None = None, calendar: ExchangeCalendar | None = None,
               live: LiveGridBars | None = None,
               now: Callable[[], datetime] | None = None,
               temporal: BarSource | None = None) -> FastAPI:
    """Migrate the store, then serve the studies routes, Rita's chart tools and the
    document API. Tests: `bars` replaces both providers' OdpBars, `calendar` the ODP
    holiday calendar (with `bars` injected and no `calendar`, none is used), `live`
    the live-grid source, `now` the composition's clock and `temporal` TemporalDB Gold."""
    store = Store(os.environ.get("ARTS_CHARTS_DB", DEFAULT_URL))
    store.migrate()  # at service start, before the first request (spec S5)
    if bars is None:
        auth = odp_credentials(os.environ)
        url = os.environ["ARTS_CHARTS_ODP_URL"]
        calendar = ExchangeCalendar(url, auth=auth)
        # The calendar restamps yfinance's months with their first trading day.
        history = {p: OdpBars(url, auth=auth, provider=p, calendar=calendar)
                   for p in ("yfinance", "eodhd")}
        # An extended intraday chart's yfinance history carries pre and after hours.
        extended = {"yfinance": OdpBars(url, auth=auth, provider="yfinance", prepost=True)}
    else:
        history, extended = {"yfinance": bars, "eodhd": bars}, {}
    if temporal is None and os.environ.get("ARTS_CHARTS_TEMPORAL_URL"):
        token = os.environ.get("ARTS_CHARTS_TEMPORAL_TOKEN")
        if not token:
            raise SystemExit("ARTS_CHARTS_TEMPORAL_TOKEN is required with ARTS_CHARTS_TEMPORAL_URL")
        try:
            temporal = TemporalGoldBars(
                os.environ["ARTS_CHARTS_TEMPORAL_URL"], token,
                os.environ.get("ARTS_CHARTS_TEMPORAL_DATASET", DEFAULT_DATASET))
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    if temporal is not None:
        history["temporaldb"] = temporal
    default = default_provider()
    if default not in history:
        raise SystemExit(f"ARTS_CHARTS_DEFAULT_PROVIDER must be one of {', '.join(history)}")
    if live is None and os.environ.get("ARTS_CHARTS_LIVE_GRID_URL"):
        live = LiveGridBars(os.environ["ARTS_CHARTS_LIVE_GRID_URL"], auth=StackAuth())
    composed = ComposedBars(history, live, calendar, now, extended)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with tools.session_manager.run():
            yield
        await snapshots.close()
        await api.aclose()

    app = FastAPI(title="arts-charts", lifespan=lifespan)
    # router() loads the operator's custom studies into the registry, so it
    # is built first: the document API and the tools read that registry.
    app.include_router(router(composed, calendar, default))
    # Before documents_router: /charts/{chart_id} would otherwise read `widgets.json` as an id.
    app.include_router(companions_router(store))
    # The tools reach this app's own routes in-process: same validation,
    # revision checks and change feed as a card's request.
    # It passes through the auth middleware like any client, so it carries the pair.
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://arts-charts",
                            auth=StackAuth())
    snapshots = Snapshots(api, Path(os.environ.get("ARTS_CHARTS_RENDER_DIR", DEFAULT_RENDER_DIR)))
    tools = chart_mcp(api, snapshots, store)
    # Mounted as a route at the exact path (a Mount would 307 `/charts/mcp` to
    # `/charts/mcp/` on the request's own Host), ahead of `/charts/{chart_id}`.
    # No Host check: like the REST routes beside it, the endpoint sits behind
    # the stack's API credentials (auth.py), which a Host allow-list here
    # would have to repeat.
    app.router.routes.extend(tools.streamable_http_app(
        streamable_http_path=MCP_PATH, stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    ).routes)
    app.include_router(snapshot_router(snapshots))
    app.include_router(kept_snapshot_router(store))
    feed = Feed()
    app.include_router(watches_router(store, feed))
    app.include_router(schedules_router(store, feed))

    async def render(chart_id: str) -> bytes:
        return (await snapshots.render(chart_id))[0]
    app.include_router(inbox_router(store, feed, render))
    app.include_router(documents_router(store, feed))
    # Appended, not add_middleware (which would put it outermost): the stack's pair is
    # demanded of every path, MCP, SSE and websockets included.
    app.user_middleware.append(Middleware(BasicAuthMiddleware))
    return app
