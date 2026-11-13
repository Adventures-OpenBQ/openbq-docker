# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Snapshots (spec §5, S11): the real chart card, rendered by headless Chromium.

Chromium loads the client package's render page (client/render, built to
ARTS_CHARTS_RENDER_DIR) on `?chart_id=`, so the card opens the document
exactly as a BDOBB card does. Every request the page makes is answered here,
in-process, from this app -- the page itself, the document (pinned to the
revision being rendered; the page never writes it), /series, the registry,
and /ta_series_ws's first frame, which is /ta_snapshot's payload -- and
anything else is aborted, so the page reaches nothing but this app.

One render at a time (spec: "serialized in-process"), at most QUEUE waiting;
one Chromium, launched on the first snapshot and kept. Runtime requirement:
the `snapshots` extra (Playwright) and its headless Chromium,
`playwright install --only-shell chromium`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from arts_charts.anchors import fixed_range
from arts_charts.store import NotFound, Store, is_chart_id

#: The page's origin. It never resolves: every request to it is answered by route().
ORIGIN = "http://render.invalid"
#: The render page as built in a source checkout (client/render/dist).
DEFAULT_RENDER_DIR = Path(__file__).resolve().parents[2] / "client" / "render" / "dist"
WIDTH, HEIGHT = 1200, 675
MIN_SIZE, MAX_SIZE = (320, 200), (2400, 1600)
#: Seconds with no request from the page before the card counts as drawn.
QUIET = 0.5
#: Seconds one render may take, from launch to PNG.
TIMEOUT = 20.0
#: Requests that may wait for the renderer before more are refused.
QUEUE = 4
#: True once the card's watermark -- the Arts Charts mark -- is drawn.
MARKED = ("() => { const m = document.querySelector('img.chart-watermark');"
          " return m !== null && m.complete && m.naturalWidth > 0; }")
#: The keys of /ta_series_ws's first frame (router.ta_series_ws) in a /ta_snapshot payload.
FRAME = ("symbol", "subtitle", "marks", "candles", "panes")
NEED_CHROMIUM = ("snapshots need Chromium: install the arts_charts[snapshots] extra, "
                 "then `playwright install --only-shell chromium`")


class SnapshotError(Exception):
    """Why no snapshot: an HTTP status and a reason that names no path or upstream."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def _symbols(body: dict) -> str:
    """The card's symbol box as the document holds it: the whole list (spec 2026-11-13 §4)."""
    return ",".join(body.get("symbols") or [body["symbol"]])


class _Page:
    """One render's answers to the page, and what they show about its progress."""

    def __init__(self, api: httpx.AsyncClient, render_dir: Path, doc: dict):
        # A relative saved range is withheld from the card, so the picture's window ends
        # today like describe_chart's; a fixed one is kept (chart_tools.compute_query).
        body = doc["body"] if fixed_range(doc["body"]) else {
            k: v for k, v in doc["body"].items() if k != "range"}
        self.api, self.dir, self.doc = api, render_dir, {**doc, "body": body}
        self.framed = False
        #: Requests the page is still waiting on: an overlay's /series may outlast QUIET.
        self.inflight = 0
        #: (status, reason) once the render cannot succeed; settled() raises it at once.
        self.failure: tuple[int, str] | None = None
        self.last = asyncio.get_running_loop().time()

    def touch(self) -> None:
        self.last = asyncio.get_running_loop().time()

    async def http(self, route) -> None:
        url = urlsplit(route.request.url)
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            await route.abort()
            return
        path, chart = url.path, f"/charts/{self.doc['id']}"
        if path == "/charts/events":
            # A feed that opens and ends: the card's sync runs on every open (step 1b
            # ruling 8), and its 1 s reconnects are not activity.
            await route.fulfill(status=200, content_type="text/event-stream", body="retry: 1000\n\n")
            return
        if path == "/charts":
            body = self.doc["body"]
            await route.fulfill(json=[{**{k: v for k, v in self.doc.items() if k != "body"},
                                       "symbol": _symbols(body), "interval": body["interval"]}])
            return
        self.touch()
        if path == "/" or path.startswith("/assets/"):
            file = (self.dir / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if file.is_relative_to(self.dir.resolve()) and file.is_file():
                await route.fulfill(path=str(file))
            else:
                await route.fulfill(status=404)
        elif path == chart:
            # Read or (should the card ever save) written: the pinned document either way.
            await route.fulfill(json=self.doc)
        else:
            request = route.request
            self.inflight += 1
            try:
                response = await self.api.request(
                    request.method, path, params=url.query, content=request.post_data_buffer)
            finally:
                self.inflight -= 1
            if path == "/series" and response.status_code != 200:
                self.failure = (502, "bars unavailable")
            await route.fulfill(status=response.status_code, body=response.content,
                                content_type=response.headers.get("content-type"))
        self.touch()

    async def ws(self, ws) -> None:
        self.touch()
        url = urlsplit(ws.url)
        if url.path != "/ta_series_ws":
            await ws.close()
            return
        response = await self.api.get("/ta_snapshot", params=url.query)
        if response.status_code == 200:
            payload = response.json()
            ws.send(json.dumps({"type": "series", "rev": 0, **{k: payload[k] for k in FRAME}}))
            self.framed = True
        elif response.status_code == 502:
            self.failure = (502, "bars unavailable")
        else:  # what the socket itself closes with: a refusal, a bad study
            detail = response.json().get("detail", "")
            self.failure = (422, f"the chart's studies were refused: {detail}")
            await ws.close(code=1011, reason=detail[:123])
        self.touch()

    async def settled(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if self.failure:
                raise SnapshotError(*self.failure)
            if self.framed and self.inflight == 0 and loop.time() - self.last >= QUIET:
                return
            await asyncio.sleep(0.05)


class Snapshots:
    """PNGs of chart documents, one render at a time."""

    def __init__(self, api: httpx.AsyncClient, render_dir: Path = DEFAULT_RENDER_DIR):
        self.api, self.dir = api, Path(render_dir)
        self._lock = asyncio.Lock()
        self._waiting = 0
        self._playwright = self._browser = None

    async def render(self, chart_id: str, width: int = WIDTH, height: int = HEIGHT,
                     theme: str = "dark", doc: dict | None = None) -> tuple[bytes, dict]:
        """(PNG, {revision, width, height}) of the document's current revision, or of
        `doc` when the caller already read it (so its numbers and the picture agree)."""
        if not (MIN_SIZE[0] <= width <= MAX_SIZE[0] and MIN_SIZE[1] <= height <= MAX_SIZE[1]):
            raise SnapshotError(422, f"a snapshot is {MIN_SIZE[0]}-{MAX_SIZE[0]} wide and "
                                     f"{MIN_SIZE[1]}-{MAX_SIZE[1]} high")
        if theme not in ("dark", "light"):
            raise SnapshotError(422, "theme is dark or light")
        if not (self.dir / "index.html").is_file():
            raise SnapshotError(503, "snapshots need the render page: in client/, "
                                     "`npx vite build -c vite.render.config.ts`, and "
                                     "ARTS_CHARTS_RENDER_DIR at client/render/dist")
        if doc is None:
            response = (await self.api.get(f"/charts/{chart_id}") if is_chart_id(chart_id)
                        else None)  # not an id: `events` is the feed's route, which never ends
            if response is None or response.status_code == 404:
                raise SnapshotError(404, "no such chart")
            doc = response.json()
        if self._waiting >= QUEUE:
            raise SnapshotError(503, "the snapshot renderer is busy; try again shortly")
        self._waiting += 1
        try:
            async with self._lock:
                png = await asyncio.wait_for(self._render(doc, width, height, theme), TIMEOUT)
        except TimeoutError:
            raise SnapshotError(504, f"the snapshot did not finish within {TIMEOUT:g} s") from None
        finally:
            self._waiting -= 1
        return png, {"revision": doc["revision"], "width": width, "height": height}

    async def _chromium(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        try:
            from playwright.async_api import async_playwright  # the snapshots extra
        except ImportError:
            raise SnapshotError(503, NEED_CHROMIUM) from None
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch()
        except Exception:  # noqa: BLE001 - Playwright's text names local paths; say what to do
            raise SnapshotError(503, NEED_CHROMIUM) from None
        return self._browser

    async def _render(self, doc: dict, width: int, height: int, theme: str) -> bytes:
        browser = await self._chromium()
        context = await browser.new_context(viewport={"width": width, "height": height})
        try:
            page = await context.new_page()
            answers = _Page(self.api, self.dir, doc)
            await page.route("**/*", answers.http)
            await page.route_web_socket("**", answers.ws)
            query = urlencode({"chart_id": doc["id"], "symbol": _symbols(doc["body"]),
                               "interval": doc["body"]["interval"], "theme": theme})
            await page.goto(f"{ORIGIN}/?{query}")
            await answers.settled()
            try:
                await page.wait_for_function(MARKED, timeout=2000)
            except Exception:  # noqa: BLE001 - Playwright's TimeoutError
                raise SnapshotError(500, "the render page drew no Arts Charts mark") from None
            return await page.screenshot(type="png")
        finally:
            await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()


def snapshot_router(snapshots: Snapshots) -> APIRouter:
    api = APIRouter()

    @api.get("/charts/{chart_id}/snapshot.png")
    async def snapshot(chart_id: str, width: int = WIDTH, height: int = HEIGHT,
                       theme: str = "dark"):
        try:
            png, meta = await snapshots.render(chart_id, width, height, theme)
        except SnapshotError as exc:
            return JSONResponse({"detail": exc.reason}, status_code=exc.status)
        return Response(png, media_type="image/png", headers={
            "Cache-Control": "no-store", "X-Chart-Revision": str(meta["revision"])})

    return api


def kept_snapshot_router(store: Store) -> APIRouter:
    """`GET /charts/{chart_id}/snapshots/{snapshot_id}.png`: a PNG snapshot_chart kept for a
    chat, by id -- the picture Rita described, not a new render. 404 when either id is not
    an id, the two do not belong together, or the purge took it."""
    api = APIRouter()

    @api.get("/charts/{chart_id}/snapshots/{snapshot_id}.png")
    async def kept(chart_id: str, snapshot_id: str):
        if not (is_chart_id(chart_id) and is_chart_id(snapshot_id)):
            return JSONResponse({"detail": "no such snapshot"}, status_code=404)
        try:
            png = await asyncio.to_thread(store.chart_snapshot_png, chart_id, snapshot_id)
        except NotFound:
            return JSONResponse({"detail": "no such snapshot"}, status_code=404)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    return api
