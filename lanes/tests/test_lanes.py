# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""D8 worker lane: heavy routes run in a child process the API can kill."""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

os.environ["OPENBQ_ROLE"] = "worker"  # importing the module must not spawn the production lane
os.environ["OPENBQ_EXTRA_APPS"] = "/nonexistent/bdobb_apps.json"  # tests set their own extras
os.environ.setdefault("OPENBQ_FIXTURES", "/nonexistent-openbq-fixtures")  # FixtureTest sets its own
sys.path.insert(0, str(Path(__file__).parents[1]))
import openbq_lanes  # noqa: E402
from collections import OrderedDict
from unittest import mock
import pandas as pd
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

FAKE = [sys.executable, str(Path(__file__).with_name("fake_worker.py"))]


class LaneTest(unittest.IsolatedAsyncioTestCase):
    def make(self, startup=0, cors=None, **options):
        self.tmp = tempfile.mkdtemp()
        sock = os.path.join(self.tmp, "lane.sock")
        options.setdefault("deadline", 20.0)
        self.lane = openbq_lanes.Lane([*FAKE, sock, str(startup)], sock, prefixes=["/api/v1/cftc/"], **options)
        self.lane.start()
        app = FastAPI()

        @app.get("/ping")
        async def ping():
            return {"ok": True}

        self.builds = 0

        @app.get("/widgets.json")
        async def widgets():
            self.builds += 1
            return {"build": self.builds}

        @app.get("/apps.json")
        async def apps():
            self.builds += 1
            return [{"build": self.builds}]  # a list, as openbb-api's apps.json

        if cors:
            app.add_middleware(CORSMiddleware, allow_origins=cors)
        app.middleware("http")(self.lane.handle)  # added last: outside CORS, as openbb-api registers hooks
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api", timeout=60)
        self.direct = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=sock), base_url="http://api", timeout=60)

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.direct.aclose()
        self.lane.stop()

    async def test_forwarded_response_is_byte_equal_to_the_worker(self):
        self.make()
        via = await self.client.post("/api/v1/cftc/echo?a=1&b=two", content=b'{"k": 1}', headers={"x-test": "t"})
        direct = await self.direct.post("/api/v1/cftc/echo?a=1&b=two", content=b'{"k": 1}', headers={"x-test": "t"})
        self.assertEqual(via.status_code, 200)
        self.assertEqual(via.content, direct.content)
        self.assertEqual(via.headers["content-type"], direct.headers["content-type"])
        self.assertNotEqual(via.json()["pid"], os.getpid())

    async def test_other_routes_stay_in_process(self):
        self.make()
        self.assertEqual((await self.client.get("/ping")).json(), {"ok": True})

    async def test_preflight_requests_stay_in_process(self):
        self.make()
        self.lane.stop()
        response = await self.client.options("/api/v1/cftc/echo")
        self.assertEqual(response.status_code, 404)  # the API's own answer: the test app has no such route
        self.assertEqual(self.lane.restarts, 0)  # a forwarded request would have respawned the lane

    async def test_the_widget_catalog_is_built_once_and_then_served_as_is(self):
        self.make()
        first = await self.client.get("/widgets.json")
        again = await self.client.get("/widgets.json")
        self.assertEqual((first.json(), again.content, self.builds), ({"build": 1}, first.content, 1))
        self.assertEqual(again.headers["content-type"], first.headers["content-type"])
        with_query = await self.client.get("/widgets.json?refresh=1")
        self.assertEqual(with_query.json(), {"build": 2})  # anything but the plain catalog is not cached

    async def test_a_browser_gets_cors_headers_from_a_catalog_cached_without_an_origin(self):
        self.make(cors=["*"])
        await self.client.get("/widgets.json")  # a probe without Origin builds the cache
        browser = await self.client.get("/widgets.json", headers={"origin": "http://localhost:4443"})
        self.assertEqual((browser.headers.get("access-control-allow-origin"), self.builds), ("*", 1))

    async def test_a_cached_catalog_answers_each_origin_for_itself(self):
        self.make(cors=["https://a.example", "https://b.example"])
        a = await self.client.get("/apps.json", headers={"origin": "https://a.example"})
        b = await self.client.get("/apps.json", headers={"origin": "https://b.example"})
        c = await self.client.get("/apps.json", headers={"origin": "https://c.example"})
        self.assertEqual(a.headers.get("access-control-allow-origin"), "https://a.example")
        self.assertEqual(b.headers.get("access-control-allow-origin"), "https://b.example")
        self.assertNotIn("access-control-allow-origin", c.headers)
        self.assertEqual((b.json(), self.builds), ([{"build": 1}], 1))

    async def test_extra_apps_join_the_cached_apps_catalog_once(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"name": "Example"}], f)
        self.addCleanup(setattr, openbq_lanes, "EXTRA_APPS", openbq_lanes.EXTRA_APPS)
        openbq_lanes.EXTRA_APPS = f.name
        self.make(cors=["*"])
        await self.client.get("/apps.json")  # a probe without Origin builds the cache
        for _ in range(2):
            browser = await self.client.get("/apps.json", headers={"origin": "http://localhost:4443"})
            self.assertEqual(browser.json(), [{"build": 1}, {"name": "Example"}])
            self.assertEqual(int(browser.headers["content-length"]), len(browser.content))
            self.assertEqual(browser.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(self.builds, 1)

    async def test_answers_made_by_the_lane_carry_cors_headers(self):
        self.make(cors=["*"], max_bytes=1000)
        origin = {"origin": "http://localhost:4443"}
        refused = await self.client.get("/api/v1/cftc/big?n=2000", headers=origin)
        status = await self.client.get("/openbq/lanes", headers=origin)
        forwarded = await self.client.get("/api/v1/cftc/big?n=500", headers=origin)
        self.assertEqual(refused.status_code, 413)
        for response in (refused, status):
            self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(forwarded.status_code, 200)  # the worker's own answer passes through unchanged

    async def test_api_answers_while_the_lane_spins(self):
        self.make()
        spin = asyncio.create_task(self.client.get("/api/v1/cftc/spin?seconds=4"))
        await asyncio.sleep(0.5)
        for _ in range(10):
            started = time.monotonic()
            self.assertEqual((await self.client.get("/ping")).status_code, 200)
            self.assertLess(time.monotonic() - started, 0.25)
            await asyncio.sleep(0.1)
        self.assertEqual((await spin).status_code, 200)

    async def test_hard_deadline_kills_the_lane_and_the_next_call_succeeds(self):
        self.make(deadline=3.0)
        first = (await self.client.get("/api/v1/cftc/echo")).json()["pid"]
        started = time.monotonic()
        response = await self.client.get("/api/v1/cftc/spin?seconds=60")
        self.assertEqual(response.status_code, 504)
        self.assertLess(time.monotonic() - started, 5)
        with self.assertRaises(ProcessLookupError):
            os.kill(first, 0)
        again = await self.client.get("/api/v1/cftc/echo")
        self.assertEqual(again.status_code, 200)
        self.assertNotEqual(again.json()["pid"], first)

    async def test_a_worker_still_starting_is_not_killed_at_the_deadline(self):
        self.make(startup=3, deadline=1.0)
        pid = self.lane.proc.pid
        response = await self.client.get("/api/v1/cftc/echo")
        self.assertEqual(response.status_code, 503)
        self.assertIn("retry-after", response.headers)
        self.assertEqual(self.lane.restarts, 0)
        await asyncio.sleep(3)
        again = await self.client.get("/api/v1/cftc/echo")
        self.assertEqual((again.status_code, again.json()["pid"]), (200, pid))

    async def test_a_worker_that_never_finishes_starting_is_replaced(self):
        self.make(startup=60, deadline=1.0, startup_limit=2.0)
        hung = self.lane.proc.pid
        await self.client.get("/api/v1/cftc/echo")  # 503: still starting, too young to replace
        self.assertEqual(self.lane.restarts, 0)
        await asyncio.sleep(1.5)
        await self.client.get("/api/v1/cftc/echo")  # past the startup limit: replaced
        self.assertEqual(self.lane.restarts, 1)
        self.assertNotEqual(self.lane.proc.pid, hung)

    async def test_the_worker_is_asked_for_an_unencoded_body_unless_the_client_says_otherwise(self):
        self.make()
        request = self.client.build_request("GET", "/api/v1/cftc/echo")
        del request.headers["accept-encoding"]
        self.assertEqual((await self.client.send(request)).json()["accept-encoding"], "identity")
        asked = await self.client.get("/api/v1/cftc/echo", headers={"accept-encoding": "gzip"})
        self.assertEqual(asked.json()["accept-encoding"], "gzip")

    async def test_a_second_call_queues_behind_the_first(self):
        self.make()
        await self.client.get("/api/v1/cftc/echo")  # lane up
        started = time.monotonic()
        results = await asyncio.gather(*(self.client.get("/api/v1/cftc/sleep?seconds=1") for _ in range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertGreaterEqual(time.monotonic() - started, 1.9)

    async def test_a_full_queue_answers_503_with_retry_after(self):
        self.make(queue_max=1)
        await self.client.get("/api/v1/cftc/echo")
        results = await asyncio.gather(*(self.client.get("/api/v1/cftc/sleep?seconds=1") for _ in range(3)))
        busy = [r for r in results if r.status_code == 503]
        self.assertEqual(len(busy), 1)
        self.assertIn("retry-after", busy[0].headers)

    async def test_a_dead_worker_answers_502_and_is_respawned(self):
        self.make()
        pid = (await self.client.get("/api/v1/cftc/echo")).json()["pid"]
        call = asyncio.create_task(self.client.get("/api/v1/cftc/sleep?seconds=5"))
        await asyncio.sleep(0.5)
        os.kill(pid, 9)
        self.assertEqual((await call).status_code, 502)
        again = await self.client.get("/api/v1/cftc/echo")
        self.assertEqual(again.status_code, 200)
        self.assertNotEqual(again.json()["pid"], pid)

    async def test_an_oversized_result_is_refused_with_413(self):
        self.make(max_bytes=1000)
        self.assertEqual((await self.client.get("/api/v1/cftc/big?n=2000")).status_code, 413)
        small = await self.client.get("/api/v1/cftc/big?n=500")
        self.assertEqual((small.status_code, len(small.content)), (200, 500))

    @unittest.skipUnless(os.path.exists("/proc/self/status"), "worker RSS is read from /proc (Linux only)")
    async def test_the_lane_is_recycled_when_its_memory_passes_the_cap(self):
        self.make(rss_mb=300)
        pid = (await self.client.get("/api/v1/cftc/hog?mb=400")).json()["pid"]
        again = await self.client.get("/api/v1/cftc/echo")
        self.assertNotEqual(again.json()["pid"], pid)

    async def test_spawning_sweeps_orphaned_shard_temp_files(self):
        shards = Path(tempfile.mkdtemp())
        (shards / "a.parquet.tmp123").write_bytes(b"")
        (shards / "a.parquet").write_bytes(b"")
        self.make(shard_dir=str(shards))
        self.assertEqual(sorted(p.name for p in shards.iterdir()), ["a.parquet"])

    async def test_status_endpoint_reports_the_lane(self):
        self.make()
        pid = (await self.client.get("/api/v1/cftc/echo")).json()["pid"]
        status = (await self.client.get("/openbq/lanes")).json()
        self.assertEqual(status["heavy"]["pid"], pid)


class NoLaneTest(unittest.IsolatedAsyncioTestCase):
    """With OPENBQ_ISOLATE empty there is no lane, but the catalogs keep their cache, extras and CORS."""

    async def test_with_the_lane_off_the_catalog_and_extra_apps_are_still_served(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"name": "Example"}], f)
        self.addCleanup(setattr, openbq_lanes, "EXTRA_APPS", openbq_lanes.EXTRA_APPS)
        openbq_lanes.EXTRA_APPS = f.name
        self.assertIsNone(openbq_lanes.LANE)  # OPENBQ_ISOLATE empty: no lane in this process
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)
        builds = []
        app = FastAPI()

        @app.get("/apps.json")
        async def apps():
            builds.append(1)
            return [{"build": len(builds)}]

        app.add_middleware(CORSMiddleware, allow_origins=["*"])
        app.middleware("http")(openbq_lanes.middleware)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
            await client.get("/apps.json")  # a probe without Origin builds the cache
            for _ in range(2):
                browser = await client.get("/apps.json", headers={"origin": "http://localhost:4443"})
                self.assertEqual(browser.json(), [{"build": 1}, {"name": "Example"}])
                self.assertEqual(int(browser.headers["content-length"]), len(browser.content))
                self.assertEqual(browser.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(len(builds), 1)


    async def test_providers_json_lists_names_and_follows_basic_auth(self):
        app = FastAPI()
        app.middleware("http")(openbq_lanes.middleware)
        self.addCleanup(setattr, openbq_lanes, "_provider_credentials", openbq_lanes._provider_credentials)
        openbq_lanes._provider_credentials = lambda: {"fred": ["fred_api_key"], "cftc": ["cftc_app_token"], "sec": []}
        os.environ.update(OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p")
        for name in ("OPENBB_API_AUTH", "OPENBB_API_USERNAME", "OPENBB_API_PASSWORD"):
            self.addCleanup(os.environ.pop, name)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
            self.assertEqual((await client.get("/providers.json")).status_code, 401)
            body = (await client.get("/providers.json", auth=("u", "p"))).json()
        self.assertEqual([(p["id"], p["auth"], p["env_vars"]) for p in body], [
            ("cftc", "optional", ["CFTC_APP_TOKEN"]),
            ("fred", "required", ["FRED_API_KEY"]),
            ("sec", "not_required", []),
        ])
        self.assertEqual(body[1]["name"], "FRED")

    async def test_the_catalogues_are_open_with_auth_on_and_built_with_the_stacks_pair(self):
        # User ruling 2026-10-19: /widgets.json and /apps.json stay open when OPENBB_API_AUTH
        # is on (credentials.env.example always said so; the image's HEALTHCHECK and BDOBB's
        # catalogue probe call them without a credential). Data routes keep the lock. The
        # cache is built through openbb-api, whose own Basic auth would refuse an anonymous
        # build, so the build carries the stack's pair -- never the caller's.
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)
        app = FastAPI()
        seen = []

        @app.get("/widgets.json")
        async def widgets(request: Request):
            seen.append(request.headers.get("authorization"))
            if request.headers.get("authorization") != "Basic dTpw":  # the API's Basic auth dependency
                return JSONResponse({"detail": "Unauthorized"}, 401)
            return {"w": {"name": "x"}}

        @app.get("/apps.json")
        async def apps(request: Request):
            seen.append(request.headers.get("authorization"))
            if request.headers.get("authorization") != "Basic dTpw":
                return JSONResponse({"detail": "Unauthorized"}, 401)
            return []

        app.middleware("http")(openbq_lanes.middleware)
        with mock.patch.dict(os.environ, OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                wrong = await client.get("/widgets.json", auth=("u", "x"))  # the miss: its header is replaced
                anon = await client.get("/widgets.json")
                apps_anon = await client.get("/apps.json")
        self.assertEqual((anon.status_code, wrong.status_code, apps_anon.status_code), (200, 200, 200))
        self.assertEqual(anon.json(), {"w": {"name": "x"}})
        self.assertEqual(seen, ["Basic dTpw", "Basic dTpw"])  # one build each, with the stack's pair


class SsrmCatalogTest(unittest.IsolatedAsyncioTestCase):
    """Listed widgets become ssrm_table pointing at <route>/ssrm; everything else is byte-identical."""

    async def asyncSetUp(self):
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)
        self.addCleanup(setattr, openbq_lanes, "SSRM_ROUTES", openbq_lanes.SSRM_ROUTES)
        openbq_lanes.SSRM_ROUTES = {
            "/api/v1/cftc/swap_trades": "cftc_swap_trades_cftc_obb",
            "/api/v1/absent/route": "absent_widget_obb",  # listed but not in widgets.json: skipped
        }

    async def serve(self):
        app = FastAPI()

        @app.get("/widgets.json")
        async def widgets_json():
            return {
                "cftc_swap_trades_cftc_obb": {
                    "name": "Swap trades", "type": "table",
                    "endpoint": "/api/v1/cftc/swap_trades",
                    "params": [{"paramName": "start_date"}], "category": "CFTC",
                },
                "other_obb": {"name": "Other", "type": "table", "endpoint": "/api/v1/other"},
            }

        app.middleware("http")(openbq_lanes.middleware)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            return (await client.get("/widgets.json")).json()

    async def test_listed_widget_is_rewritten_and_others_are_untouched(self):
        body = await self.serve()
        listed = body["cftc_swap_trades_cftc_obb"]
        self.assertEqual(listed["type"], "ssrm_table")
        self.assertEqual(listed["endpoint"], "/api/v1/cftc/swap_trades/ssrm")
        self.assertEqual(listed["ssrm"], {"sorting": True, "filtering": ["text", "number"]})
        self.assertEqual(listed["name"], "Swap trades")          # other fields kept
        self.assertEqual(listed["params"], [{"paramName": "start_date"}])
        self.assertEqual(listed["category"], "CFTC")
        self.assertEqual(body["other_obb"], {"name": "Other", "type": "table", "endpoint": "/api/v1/other"})
        self.assertNotIn("absent_widget_obb", body)              # listed-but-absent skipped, no error

    def test_the_committed_list_has_23_widgets_with_ssrm_routes(self):
        routes = openbq_lanes._load_ssrm_widgets(Path(__file__).parent.parent / "ssrm_widgets.json")
        self.assertEqual(len(routes), 23)
        self.assertTrue(all(r.startswith("/api/v1/") for r in routes))


class SsrmLaneTest(unittest.IsolatedAsyncioTestCase):
    make = LaneTest.make  # a real lane, without re-running LaneTest's own tests
    asyncTearDown = LaneTest.asyncTearDown

    async def test_a_lane_route_is_acquired_through_its_lane(self):
        self.make()
        for name in ("LANE", "SSRM_ROUTES", "SSRM_CACHE"):
            self.addCleanup(setattr, openbq_lanes, name, getattr(openbq_lanes, name))
        openbq_lanes.LANE = self.lane
        openbq_lanes.SSRM_ROUTES = {"/api/v1/cftc/rows": "rows_obb"}
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        app = FastAPI()
        app.middleware("http")(openbq_lanes.middleware)
        body = {"startRow": 0, "endRow": 10, "sortModel": [], "filterModel": {}, "rowGroupCols": [],
                "groupKeys": [], "valueCols": [], "pivotCols": [], "pivotMode": False}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api", timeout=60) as c:
            r = await c.post("/api/v1/cftc/rows/ssrm", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["rowData"][0]["pid"], os.getpid())  # the worker answered the GET


class SsrmRowsTest(unittest.IsolatedAsyncioTestCase):
    """POST <route>/ssrm pages, filters and sorts the cached result; refuses the rest."""

    def app(self):
        self.gets = 0
        self.seen_auth = []
        self.rows = [
            {"name": "Alpha", "value": 3, "when": "2026-01-03"},
            {"name": "beta", "value": 1, "when": "2026-01-01"},
            {"name": "Gamma", "value": 2, "when": "2026-01-02"},
        ]
        app = FastAPI()

        @app.get("/api/v1/listed/data")
        async def data(request: Request):
            self.gets += 1
            self.seen_auth.append(request.headers.get("authorization"))
            if request.query_params.get("boom") == "1":
                return JSONResponse({"detail": "sanitised upstream error"}, 503)
            if request.query_params.get("text") == "1":
                return Response("not json", 200, media_type="text/plain")
            if request.query_params.get("empty") == "1":
                return {"results": []}
            # json.dumps writes NaN as the bare token, as a NaN-carrying upstream would
            return Response(json.dumps({"results": self.rows}), media_type="application/json")

        app.middleware("http")(openbq_lanes.middleware)
        return app

    async def asyncSetUp(self):
        self.addCleanup(setattr, openbq_lanes, "SSRM_ROUTES", openbq_lanes.SSRM_ROUTES)
        self.addCleanup(setattr, openbq_lanes, "SSRM_CACHE", openbq_lanes.SSRM_CACHE)
        openbq_lanes.SSRM_ROUTES = {"/api/v1/listed/data": "listed_obb"}
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)

    def client(self, app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")

    def req(self, **over):
        body = {"startRow": 0, "endRow": 100, "sortModel": [], "filterModel": {},
                "rowGroupCols": [], "groupKeys": [], "valueCols": [], "pivotCols": [], "pivotMode": False}
        body.update(over)
        return body

    async def test_new_views_are_built_at_most_ssrm_slots_at_a_time(self):
        import threading
        app = self.app()
        running, peak, lock = [0], [0], threading.Lock()
        view_order = openbq_lanes._view_order

        def counted(df, body):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.2)
            with lock:
                running[0] -= 1
            return view_order(df, body)

        async with self.client(app) as c:
            await c.post("/api/v1/listed/data/ssrm", json=self.req())  # acquire the frame once
            with mock.patch.object(openbq_lanes, "_view_order", counted):
                replies = await asyncio.gather(*[
                    c.post("/api/v1/listed/data/ssrm", json=self.req(
                        filterModel={"value": {"filterType": "number", "type": "greaterThanOrEqual", "filter": n}}))
                    for n in range(6)])
        self.assertEqual({r.status_code for r in replies}, {200})
        self.assertEqual(peak[0], openbq_lanes.SSRM_SLOTS)

    async def test_first_page_sorted_and_counted(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(sortModel=[{"colId": "value", "sort": "asc"}]))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([row["value"] for row in body["rowData"]], [1, 2, 3])
        self.assertEqual(body["rowCount"], 3)

    async def test_text_contains_is_case_insensitive(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(
                filterModel={"name": {"filterType": "text", "type": "contains", "filter": "a"}}))
        self.assertEqual({row["name"] for row in r.json()["rowData"]}, {"Alpha", "beta", "Gamma"})
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(
                filterModel={"name": {"filterType": "text", "type": "contains", "filter": "GAMM"}}))
        self.assertEqual([row["name"] for row in r.json()["rowData"]], ["Gamma"])

    async def test_number_filters(self):
        app = self.app()
        for model, expected in [
            ({"value": {"filterType": "number", "type": "inRange", "filter": 2, "filterTo": 3}}, {2, 3}),
            ({"value": {"filterType": "number", "type": "greaterThanOrEqual", "filter": 2}}, {2, 3}),
            ({"value": {"filterType": "number", "type": "lessThanOrEqual", "filter": 2}}, {1, 2}),
        ]:
            async with self.client(app) as c:
                r = await c.post("/api/v1/listed/data/ssrm", json=self.req(filterModel=model))
            self.assertEqual({row["value"] for row in r.json()["rowData"]}, expected)

    async def test_slice_and_cap(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm",
                             json=self.req(startRow=1, endRow=2, sortModel=[{"colId": "value", "sort": "asc"}]))
        self.assertEqual([row["value"] for row in r.json()["rowData"]], [2])
        self.assertEqual(r.json()["rowCount"], 3)
        async with self.client(app) as c:
            over = await c.post("/api/v1/listed/data/ssrm", json=self.req(endRow=1001))
            neg = await c.post("/api/v1/listed/data/ssrm", json=self.req(startRow=5, endRow=2))
        self.assertEqual((over.status_code, neg.status_code), (400, 400))

    async def test_page_past_the_end_is_empty_with_the_true_count(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(startRow=100, endRow=200))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["rowData"], r.json()["rowCount"]), ([], 3))

    async def test_unknown_column_is_rejected(self):
        app = self.app()
        async with self.client(app) as c:
            s = await c.post("/api/v1/listed/data/ssrm", json=self.req(sortModel=[{"colId": "nope", "sort": "asc"}]))
            f = await c.post("/api/v1/listed/data/ssrm", json=self.req(
                filterModel={"nope": {"filterType": "text", "type": "contains", "filter": "x"}}))
        self.assertEqual((s.status_code, f.status_code), (400, 400))

    async def test_grouping_values_pivot_and_bad_filters_are_refused(self):
        app = self.app()
        for over in [
            {"rowGroupCols": [{"id": "name", "field": "name"}]},
            {"groupKeys": ["Alpha"]},
            {"valueCols": [{"id": "value", "field": "value"}]},
            {"pivotCols": [{"id": "name", "field": "name"}]},
            {"pivotMode": True},
            {"filterModel": {"name": {"filterType": "set", "values": ["Alpha"]}}},
            {"filterModel": {"value": {"filterType": "number", "type": "notEqual", "filter": 1}}},
        ]:
            async with self.client(app) as c:
                r = await c.post("/api/v1/listed/data/ssrm", json=self.req(**over))
            self.assertEqual(r.status_code, 400, over)

    async def test_unlisted_route_is_404(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/other/data/ssrm", json=self.req())
        self.assertEqual(r.status_code, 404)

    async def test_results_shapes_all_become_row_lists(self):
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        self.assertEqual(openbq_lanes._rows_from({"results": [{"a": 1}]}), [{"a": 1}])
        self.assertEqual(openbq_lanes._rows_from([{"a": 1}]), [{"a": 1}])
        self.assertEqual(openbq_lanes._rows_from({"results": {"x": {"a": 1}}}), [{"a": 1}])
        self.assertEqual(openbq_lanes._rows_from({"results": None}), [])
        self.assertEqual(openbq_lanes._rows_from({"results": [1, "x"]}), [])

    async def test_reply_is_json_safe(self):
        app = self.app()
        self.rows = [{"name": "A", "value": float("nan"), "when": "2026-01-01"},
                     {"name": "B", "value": 2, "when": "2026-01-02"}]
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())
        self.assertIsNone(r.json()["rowData"][0]["value"])  # NaN -> null, parseable JSON

    async def test_acquired_once_then_served_from_cache(self):
        app = self.app()
        async with self.client(app) as c:
            await c.post("/api/v1/listed/data/ssrm", json=self.req())
            await c.post("/api/v1/listed/data/ssrm", json=self.req(startRow=1, endRow=2))
        self.assertEqual(self.gets, 1)  # second page reuses the cached frame

    async def test_concurrent_first_requests_acquire_once(self):
        app = self.app()

        @app.get("/api/v1/listed/slow")
        async def slow():
            self.gets += 1
            await asyncio.sleep(0.3)
            return {"results": list(self.rows)}

        openbq_lanes.SSRM_ROUTES = {"/api/v1/listed/slow": "slow_obb"}
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        async with self.client(app) as c:
            a, b = await asyncio.gather(
                c.post("/api/v1/listed/slow/ssrm", json=self.req()),
                c.post("/api/v1/listed/slow/ssrm", json=self.req(startRow=1, endRow=2)),
            )
        self.assertEqual((a.status_code, b.status_code), (200, 200))
        self.assertEqual(self.gets, 1)

    async def test_upstream_error_is_kept(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm?boom=1", json=self.req())
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "sanitised upstream error"})

    async def test_lru_evicts_at_the_byte_bound(self):
        cache = openbq_lanes.SsrmCache(max_bytes=1, ttl=900)
        async def df(n):
            return pd.DataFrame([{"a": i} for i in range(n)])
        await cache.get(("r", (("p", "1"),)), lambda: df(10))
        await cache.get(("r", (("p", "2"),)), lambda: df(10))
        self.assertEqual(len(cache.entries), 1)  # only the newest survives a 1-byte cap

    async def test_ttl_expiry_reacquires(self):
        clock = [0.0]
        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=10, clock=lambda: clock[0])
        calls = []
        async def acquire():
            calls.append(1)
            return pd.DataFrame([{"a": 1}])
        await cache.get(("r", ()), acquire)
        clock[0] = 11.0
        await cache.get(("r", ()), acquire)
        self.assertEqual(len(calls), 2)  # expired entry reacquired

    # -- strictness: this endpoint sits behind the public door ------------------

    async def test_malformed_bodies_are_refused(self):
        app = self.app()
        bad = [
            self.req(extra=1),                                   # unknown top-level key
            self.req(startRow=True),                             # bool is not a row index
            self.req(startRow=0.5),
            {"startRow": 0},                                     # missing keys
            self.req(sortModel=[{"colId": "value", "sort": "asc", "x": 1}]),
            self.req(sortModel={"colId": "value"}),
            self.req(filterModel=[]),
            self.req(filterModel={"value": {"filterType": "number", "type": "greaterThanOrEqual", "filter": True}}),
            self.req(filterModel={"value": {"filterType": "number", "type": "inRange", "filter": 1}}),
            self.req(filterModel={"name": {"filterType": "text", "type": "contains", "filter": "a", "extra": 1}}),
            self.req(filterModel={"name": {"filterType": "text", "operator": "AND", "conditions": []}}),
        ]
        async with self.client(app) as c:
            for body in bad:
                r = await c.post("/api/v1/listed/data/ssrm", json=body)
                self.assertEqual(r.status_code, 400, body)
            for raw in (b"not json", b'{"startRow": NaN}', b"[]", b"{" + b" " * (70 << 10) + b"}"):
                r = await c.post("/api/v1/listed/data/ssrm", content=raw)
                self.assertEqual(r.status_code, 400, raw[:20])
                self.assertNotIn("Expecting", r.text)            # no parser text reflected

    async def test_non_json_upstream_is_a_fixed_502(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm?text=1", json=self.req())
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("not json", r.text)

    async def test_an_empty_result_answers_empty_whatever_the_columns(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm?empty=1", json=self.req(
                sortModel=[{"colId": "value", "sort": "asc"}],
                filterModel={"name": {"filterType": "text", "type": "contains", "filter": "x"}}))
        self.assertEqual((r.status_code, r.json()), (200, {"rowData": [], "rowCount": 0}))

    async def test_mixed_type_column_sorts_without_failing(self):
        app = self.app()
        self.rows = [{"name": "A", "value": 2}, {"name": "B", "value": "n/a"}, {"name": "C", "value": 1}]
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(sortModel=[{"colId": "value", "sort": "asc"}]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rowCount"], 3)

    async def test_params_key_the_cache_and_reach_the_get(self):
        app = self.app()
        async with self.client(app) as c:
            await c.post("/api/v1/listed/data/ssrm?a=1", json=self.req())
            await c.post("/api/v1/listed/data/ssrm?a=2", json=self.req())
            await c.post("/api/v1/listed/data/ssrm?a=1", json=self.req())
        self.assertEqual(self.gets, 2)

    async def test_basic_auth_applies_before_the_cache_and_is_forwarded(self):
        app = self.app()
        with mock.patch.dict(os.environ, OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p"):
            async with self.client(app) as c:
                ok = await c.post("/api/v1/listed/data/ssrm", json=self.req(), auth=("u", "p"))
                anon = await c.post("/api/v1/listed/data/ssrm", json=self.req())
                wrong = await c.post("/api/v1/listed/data/ssrm", json=self.req(), auth=("u", "x"))
        self.assertEqual((ok.status_code, anon.status_code, wrong.status_code), (200, 401, 401))
        self.assertEqual(self.gets, 1)
        self.assertTrue(self.seen_auth[0].startswith("Basic "))  # the internal GET carried the caller's pair

    async def test_a_cancelled_first_caller_does_not_fail_the_one_sharing_it(self):
        gate = asyncio.Event()

        async def acquire():
            await gate.wait()
            return pd.DataFrame([{"a": 1}])

        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        first = asyncio.ensure_future(cache.get(("r", ()), acquire))
        second = asyncio.ensure_future(cache.get(("r", ()), acquire))
        await asyncio.sleep(0)
        first.cancel()
        gate.set()
        self.assertEqual(len(await second), 1)
        self.assertEqual(len(cache.entries), 1)


class SsrmFixRound1Test(unittest.IsolatedAsyncioTestCase):
    """Review fixes: acquisition cap and deadline, lossless floats, declared params, sort order."""

    req = SsrmRowsTest.req
    client = SsrmRowsTest.client

    async def asyncSetUp(self):
        for name in ("SSRM_ROUTES", "SSRM_CACHE", "_SSRM_WIDGET", "_CATALOG_CACHE"):
            self.addCleanup(setattr, openbq_lanes, name, getattr(openbq_lanes, name))
        openbq_lanes.SSRM_ROUTES = {"/api/v1/listed/data": "listed_obb"}
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        openbq_lanes._SSRM_WIDGET = {}
        openbq_lanes._CATALOG_CACHE = {}

    def app(self, rows, widgets=None, raises=False):
        self.queries = []
        app = FastAPI()

        @app.get("/api/v1/listed/data")
        async def data(request: Request):
            self.queries.append(sorted(request.query_params.multi_items()))
            if raises:
                raise RuntimeError("provider secret token=abc")
            return Response(json.dumps({"results": rows}), media_type="application/json")

        if widgets is not None:
            @app.get("/widgets.json")
            async def catalog():
                return widgets

        app.middleware("http")(openbq_lanes.middleware)
        return app

    # I1 -----------------------------------------------------------------
    async def test_at_most_two_cold_acquisitions_run_at_once(self):
        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        inside, peak = [0], [0]

        async def acquire():
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
            await asyncio.sleep(0.05)
            inside[0] -= 1
            return pd.DataFrame([{"a": 1}])

        await asyncio.gather(*(cache.get((f"k{i}", ()), acquire) for i in range(3)),
                             *(cache.get(("k0", ()), acquire) for _ in range(3)))  # waiters take no slot
        self.assertEqual(peak[0], 2)
        self.assertEqual(len(cache.entries), 3)

    # I2 -----------------------------------------------------------------
    async def test_reply_values_round_trip_exactly(self):
        rows = [{"x": 1e-12, "i": 2 ** 60, "n": {"k": [1, 2]}}, {"x": 0.123456789012345, "i": 3, "n": None}]
        app = self.app(rows)
        async with self.client(app) as c:
            full = await c.get("/api/v1/listed/data")
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())
        self.assertEqual(r.json()["rowData"], full.json()["results"])

    # I3 -----------------------------------------------------------------
    async def test_a_hung_acquisition_times_out_for_every_waiter_and_frees_its_slot(self):
        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900, deadline=0.1)

        async def hang():
            await asyncio.Event().wait()

        results = await asyncio.gather(*(cache.get(("k", ()), hang) for _ in range(3)), return_exceptions=True)
        self.assertTrue(all(isinstance(e, openbq_lanes.SsrmUpstream) and e.status == 504 for e in results))
        self.assertEqual((cache.entries, cache.inflight), (OrderedDict(), {}))

        async def ok():
            return pd.DataFrame([{"a": 1}])
        a, b = await asyncio.wait_for(asyncio.gather(cache.get(("x", ()), ok), cache.get(("y", ()), ok)), 2)
        self.assertEqual((len(a), len(b)), (1, 1))  # both slots came back

    async def test_the_endpoint_answers_a_fixed_504_past_the_deadline(self):
        app = FastAPI()

        @app.get("/api/v1/listed/data")
        async def data():
            await asyncio.sleep(5)

        app.middleware("http")(openbq_lanes.middleware)
        openbq_lanes.SSRM_CACHE = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900, deadline=0.1)
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())
        self.assertEqual(r.status_code, 504)
        self.assertEqual(set(r.json()), {"detail"})

    # M1 -----------------------------------------------------------------
    async def test_undeclared_params_are_dropped_before_the_get_and_the_key(self):
        widgets = {"listed_obb": {"params": [{"paramName": "a"}, [{"paramName": "b"}]]}}
        app = self.app([{"v": 1}], widgets)
        async with self.client(app) as c:
            for junk in ("1", "2", "3"):
                r = await c.post(f"/api/v1/listed/data/ssrm?a=1&b=2&junk={junk}", json=self.req())
                self.assertEqual(r.status_code, 200)
        self.assertEqual(self.queries, [[("a", "1"), ("b", "2")]])  # one GET, junk never sent

    async def test_rows_carry_exactly_the_declared_columns(self):
        # BDOBB's paged provider requires every row's keys to equal columnsDefs: OpenBB omits
        # None fields, so a field absent from every record must still arrive, as null.
        widgets = {"listed_obb": {"data": {"table": {"columnsDefs": [{"field": "a"}, {"field": "b"}, {"field": "c"}]}}}}
        app = self.app([{"a": 2, "b": "x", "z": 9}, {"a": 1, "z": 8}], widgets)
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req(sortModel=[{"colId": "a", "sort": "asc"}]))
            unknown = await c.post("/api/v1/listed/data/ssrm", json=self.req(sortModel=[{"colId": "z", "sort": "asc"}]))
        self.assertEqual(r.json()["rowData"], [{"a": 1, "b": None, "c": None}, {"a": 2, "b": "x", "c": None}])
        self.assertEqual(unknown.status_code, 400)  # an undeclared column is not served

    async def test_a_widget_without_declared_params_keeps_its_params_and_is_looked_up_once(self):
        app = self.app([{"v": 1}], {"listed_obb": {"name": "no params"}})
        async with self.client(app) as c:
            await c.post("/api/v1/listed/data/ssrm?a=1", json=self.req())
        self.assertEqual(self.queries, [[("a", "1")]])
        self.assertIsNone(openbq_lanes._SSRM_WIDGET["listed_obb"][0])

    # M2 -----------------------------------------------------------------
    async def test_an_inner_exception_is_an_ordinary_500_without_its_text(self):
        app = self.app([], raises=True)
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("secret", r.text)

    # M4 + M5 + M6 -------------------------------------------------------
    async def test_multi_column_sort_desc_stable_nulls_and_mixed_columns(self):
        rows = [
            {"id": 1, "g": "b", "n": 9, "m": 1},
            {"id": 2, "g": "a", "n": 10, "m": "n/a"},
            {"id": 3, "g": "b", "n": None, "m": 2},
            {"id": 4, "g": "a", "n": 10, "m": 3},
            {"id": 5, "g": None, "n": 1, "m": 4},
        ]
        app = self.app(rows)

        async def order(*sorts):
            async with self.client(app) as c:
                r = await c.post("/api/v1/listed/data/ssrm", json=self.req(
                    sortModel=[{"colId": col, "sort": d} for col, d in sorts]))
            self.assertEqual(r.status_code, 200)
            return [row["id"] for row in r.json()["rowData"]]

        # g asc (nulls first, as AG Grid), then n desc (nulls last); ties keep input order
        self.assertEqual(await order(("g", "asc"), ("n", "desc")), [5, 2, 4, 1, 3])
        # a mixed column sorts as text, but a numeric column beside it stays numeric (9 before 10)
        self.assertEqual(await order(("n", "asc"), ("m", "asc")), [3, 5, 1, 4, 2])

    async def test_a_failed_first_acquisition_reaches_every_waiter_then_retries(self):
        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900)
        calls = []

        async def boom():
            calls.append(1)
            await asyncio.sleep(0.01)
            raise openbq_lanes.SsrmUpstream(503, b"{}", "application/json")

        results = await asyncio.gather(cache.get(("k", ()), boom), cache.get(("k", ()), boom),
                                       return_exceptions=True)
        self.assertTrue(all(isinstance(e, openbq_lanes.SsrmUpstream) for e in results))
        self.assertEqual(len(calls), 1)

        async def ok():
            return pd.DataFrame([{"a": 1}])
        self.assertEqual(len(await cache.get(("k", ()), ok)), 1)

    async def test_lru_keeps_the_most_recently_used_and_counts_bytes(self):
        frame = pd.DataFrame([{"a": i} for i in range(10)])
        size = int(frame.memory_usage(deep=True).sum())
        cache = openbq_lanes.SsrmCache(max_bytes=2 * size, ttl=900)

        async def acquire():
            return frame.copy()
        for key in ("k1", "k2", "k1", "k3"):
            await cache.get((key, ()), acquire)
        self.assertEqual(list(cache.entries), [("k1", ()), ("k3", ())])
        self.assertEqual(cache.total, 2 * size)


class SsrmFixRound2Test(unittest.IsolatedAsyncioTestCase):
    """Re-review fixes: non-finite floats, one deadline over the slot wait too."""

    req = SsrmRowsTest.req
    client = SsrmRowsTest.client
    asyncSetUp = SsrmFixRound1Test.asyncSetUp
    app = SsrmFixRound1Test.app

    async def test_infinities_become_null(self):
        app = self.app([{"x": float("inf"), "m": "a"}, {"x": float("-inf"), "m": float("inf")}, {"x": 1.5, "m": "b"}])
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())  # the source JSON says Infinity
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(row["x"], row["m"]) for row in r.json()["rowData"]],
                         [(None, "a"), (None, None), (1.5, "b")])

    async def test_a_queued_acquisition_times_out_within_the_deadline_and_never_takes_a_slot(self):
        cache = openbq_lanes.SsrmCache(max_bytes=3 << 30, ttl=900, slots=1, deadline=0.2)
        started = []

        async def hang(name):
            started.append(name)
            await asyncio.Event().wait()

        t0 = time.monotonic()
        results = await asyncio.gather(cache.get(("a", ()), lambda: hang("a")),
                                       cache.get(("b", ()), lambda: hang("b")), return_exceptions=True)
        self.assertLess(time.monotonic() - t0, 0.35)  # b waited for a's slot inside its own 0.2 s
        self.assertTrue(all(isinstance(e, openbq_lanes.SsrmUpstream) and e.status == 504 for e in results))
        self.assertEqual(started, ["a"])  # b never got the slot
        self.assertFalse(cache.slots.locked())  # and nothing holds it now


class SsrmFinalFixTest(unittest.IsolatedAsyncioTestCase):
    """Final-review fixes: sort cap, hit/miss header, catalogue auth, view cache, exact ints, byte-equal catalogue."""

    req = SsrmRowsTest.req
    client = SsrmRowsTest.client
    asyncSetUp = SsrmFixRound1Test.asyncSetUp
    app = SsrmFixRound1Test.app

    async def post(self, app, path="/api/v1/listed/data/ssrm", **over):
        async with self.client(app) as c:
            return await c.post(path, json=self.req(**over))

    # I-1 ----------------------------------------------------------------
    async def test_a_repeated_or_over_long_sort_model_is_refused(self):
        app = self.app([{f"c{i}": i for i in range(20)}])
        dup = await self.post(app, sortModel=[{"colId": "c0", "sort": "asc"}, {"colId": "c0", "sort": "desc"}])
        over = await self.post(app, sortModel=[{"colId": f"c{i}", "sort": "asc"} for i in range(4)])
        ok = await self.post(app, sortModel=[{"colId": f"c{i}", "sort": "asc"} for i in range(3)])
        self.assertEqual((dup.status_code, over.status_code, ok.status_code), (400, 400, 200))
        self.assertEqual(dup.json(), {"detail": openbq_lanes._SSRM_REFUSED})

    # I-3 ----------------------------------------------------------------
    async def test_a_page_from_the_cache_says_hit_and_an_acquisition_says_miss(self):
        app = self.app([{"v": 1}])
        first = await self.post(app)
        second = await self.post(app, startRow=1, endRow=2)
        self.assertEqual(first.headers["x-openbq-ssrm"], "miss")
        self.assertEqual(second.headers["x-openbq-ssrm"], "hit")

    # M-1 ----------------------------------------------------------------
    async def test_an_uncached_catalogue_is_built_with_the_callers_authorization(self):
        app = FastAPI()
        self.queries = []

        @app.get("/widgets.json")
        async def catalog(request: Request):
            if not request.headers.get("authorization"):  # the API's Basic auth dependency
                return JSONResponse({"detail": "Unauthorized"}, 401)
            return {"listed_obb": {"params": [{"paramName": "a"}]}}

        @app.get("/api/v1/listed/data")
        async def data(request: Request):
            self.queries.append(sorted(request.query_params.multi_items()))
            return {"results": [{"v": 1}]}

        app.middleware("http")(openbq_lanes.middleware)
        with mock.patch.dict(os.environ, OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p"):
            async with self.client(app) as c:
                r = await c.post("/api/v1/listed/data/ssrm?a=1&junk=2", json=self.req(), auth=("u", "p"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.queries, [[("a", "1")]])

    # M-2 ----------------------------------------------------------------
    async def test_a_second_page_of_the_same_view_does_not_refilter_or_resort(self):
        app = self.app([{"v": i % 7, "s": f"x{i}"} for i in range(50)])
        view = {"sortModel": [{"colId": "v", "sort": "desc"}],
                "filterModel": {"s": {"filterType": "text", "type": "contains", "filter": "x"}}}
        sort_values = pd.DataFrame.sort_values
        with mock.patch.object(pd.DataFrame, "sort_values", autospec=True, side_effect=sort_values) as sorts:
            a = await self.post(app, startRow=0, endRow=10, **view)
            b = await self.post(app, startRow=10, endRow=20, **view)
            self.assertEqual(sorts.call_count, 1)
            await self.post(app, sortModel=[{"colId": "v", "sort": "asc"}])  # a new view sorts again
            self.assertEqual(sorts.call_count, 2)
        both = [row["v"] for row in a.json()["rowData"] + b.json()["rowData"]]
        self.assertEqual(both, sorted(both, reverse=True))
        self.assertEqual(b.json()["rowCount"], 50)

    async def test_at_most_eight_views_are_kept_per_frame_and_go_with_it(self):
        app = self.app([{"v": i} for i in range(20)])
        for lo in range(10):
            await self.post(app, filterModel={"v": {"filterType": "number", "type": "greaterThanOrEqual", "filter": lo}})
        (key,) = openbq_lanes.SSRM_CACHE.entries
        self.assertEqual(len(openbq_lanes.SSRM_CACHE.entries[key][3]), 8)
        openbq_lanes.SSRM_CACHE.max_bytes = 0
        await self.post(app, path="/api/v1/listed/data/ssrm?a=2")  # evicts the first frame
        self.assertNotIn(key, openbq_lanes.SSRM_CACHE.entries)

    # M-3 ----------------------------------------------------------------
    async def test_integers_past_2_53_with_nulls_stay_exact(self):
        app = self.app([{"id": 2**60 + 1}, {"id": None}, {"x": 1}])
        r = await self.post(app)
        self.assertIn(b'"id":1152921504606846977', r.content.replace(b" ", b""))
        self.assertEqual([row["id"] for row in r.json()["rowData"]], [2**60 + 1, None, None])
        f = await self.post(app, filterModel={"id": {"filterType": "number", "type": "greaterThanOrEqual", "filter": 1}})
        self.assertEqual(f.json()["rowCount"], 1)

    # M-5 ----------------------------------------------------------------
    async def test_an_unlisted_widget_is_byte_identical_to_the_original(self):
        other = {"name": "Ünïcode — “quotes”", "x": 0.1, "big": 1e300, "params": [{"paramName": "a"}]}
        catalog = {"listed_obb": {"type": "table", "endpoint": "/api/v1/listed/data"}, "other_obb": other}
        app = FastAPI()

        @app.get("/widgets.json")
        async def widgets_json():
            return JSONResponse(catalog)

        original = JSONResponse(catalog).body
        app.middleware("http")(openbq_lanes.middleware)
        async with self.client(app) as c:
            served = (await c.get("/widgets.json")).content
        piece = original[original.index(b'"other_obb"'):]
        self.assertIn(piece, served)
        self.assertEqual(json.loads(served)["listed_obb"]["type"], "ssrm_table")

    # M-6 ----------------------------------------------------------------
    async def test_number_equals_is_supported_and_combined_filters_stay_refused(self):
        app = self.app([{"v": 1}, {"v": 2}, {"v": 2}])
        eq = await self.post(app, filterModel={"v": {"filterType": "number", "type": "equals", "filter": 2}})
        self.assertEqual((eq.status_code, eq.json()["rowCount"]), (200, 2))
        combined = {"v": {"filterType": "number", "operator": "AND", "conditions": [
            {"filterType": "number", "type": "equals", "filter": 2},
            {"filterType": "number", "type": "equals", "filter": 1}]}}
        self.assertEqual((await self.post(app, filterModel=combined)).status_code, 400)


class SsrmFinalFixRound2Test(unittest.IsolatedAsyncioTestCase):
    """Re-review: hit means frame AND view reused, tighter caps, views in the byte budget, exact equals."""

    req = SsrmRowsTest.req
    client = SsrmRowsTest.client
    asyncSetUp = SsrmFixRound1Test.asyncSetUp
    app = SsrmFixRound1Test.app
    post = SsrmFinalFixTest.post

    async def test_a_novel_view_on_a_cached_frame_is_a_miss_and_its_next_page_a_hit(self):
        app = self.app([{"v": i} for i in range(5)])
        await self.post(app)  # the frame is acquired
        novel = await self.post(app, sortModel=[{"colId": "v", "sort": "desc"}])
        again = await self.post(app, startRow=2, endRow=4, sortModel=[{"colId": "v", "sort": "desc"}])
        self.assertEqual((novel.headers["x-openbq-ssrm"], again.headers["x-openbq-ssrm"]), ("miss", "hit"))
        self.assertEqual([r["v"] for r in again.json()["rowData"]], [2, 1])

    async def test_more_than_16_filters_are_refused(self):
        app = self.app([{f"c{i}": "x" for i in range(17)}])
        text = {"filterType": "text", "type": "contains", "filter": ""}
        ok = await self.post(app, filterModel={f"c{i}": text for i in range(16)})
        over = await self.post(app, filterModel={f"c{i}": text for i in range(17)})
        self.assertEqual((ok.status_code, over.status_code), (200, 400))

    async def test_view_orders_count_against_the_byte_budget(self):
        frame = pd.DataFrame([{"v": i} for i in range(100)])
        size = int(frame.memory_usage(deep=True).sum())
        app = self.app([{"v": i} for i in range(100)])
        order = 100 * 8  # one view's row positions (int64)
        # two frames and their default views fit, not a third view
        openbq_lanes.SSRM_CACHE.max_bytes = 2 * (size + order) + order // 2
        await self.post(app, path="/api/v1/listed/data/ssrm?a=1")
        await self.post(app, path="/api/v1/listed/data/ssrm?a=2")
        cache = openbq_lanes.SSRM_CACHE
        self.assertEqual(len(cache.entries), 2)
        await self.post(app, path="/api/v1/listed/data/ssrm?a=2", sortModel=[{"colId": "v", "sort": "desc"}])
        (key,) = cache.entries  # the a=2 frame's views pushed the a=1 frame out
        self.assertEqual(key[1], (("a", "2"),))
        views = cache.entries[key][3]
        self.assertEqual(cache.total, size + sum(o.nbytes for o in views.values()))

    async def test_number_equals_on_an_integer_column_is_exact(self):
        app = self.app([{"id": 2**60, "n": 2**60}, {"id": 2**60 + 1, "n": 2**60 + 1}, {"id": None, "n": 1}])
        for col in ("id", "n"):  # Int64 (has a null) and int64
            r = await self.post(app, filterModel={col: {"filterType": "number", "type": "equals", "filter": 2**60}})
            self.assertEqual([row[col] for row in r.json()["rowData"]], [2**60], col)


class SsrmWarningsTest(unittest.IsolatedAsyncioTestCase):
    """An OBBject's warnings (e.g. FINRA's MBS record cap) reach every SSRM page, hit or miss."""

    asyncSetUp, client, req = SsrmRowsTest.asyncSetUp, SsrmRowsTest.client, SsrmRowsTest.req

    def app(self):
        app = FastAPI()
        self.gets = 0

        @app.get("/api/v1/listed/data")
        async def data(request: Request):
            self.gets += 1
            body = {"results": [{"name": "Alpha", "value": 1}]}
            if request.query_params.get("capped") == "1":
                body["warnings"] = [{"category": "OpenBBWarning", "message": "Results capped at 1 record."}]
            return body

        app.middleware("http")(openbq_lanes.middleware)
        return app

    async def test_warnings_ride_every_page(self):
        app = self.app()
        async with self.client(app) as c:
            first = await c.post("/api/v1/listed/data/ssrm?capped=1", json=self.req())
            again = await c.post("/api/v1/listed/data/ssrm?capped=1", json=self.req(startRow=0, endRow=50))
        want = [{"category": "OpenBBWarning", "message": "Results capped at 1 record."}]
        self.assertEqual((first.json()["warnings"], again.json()["warnings"]), (want, want))
        self.assertEqual((again.headers["x-openbq-ssrm"], self.gets), ("hit", 1))

    async def test_no_warnings_key_without_warnings(self):
        app = self.app()
        async with self.client(app) as c:
            r = await c.post("/api/v1/listed/data/ssrm", json=self.req())
        self.assertNotIn("warnings", r.json())


class ExtraAppsTest(unittest.TestCase):
    """BDOBB's example apps are appended to a built apps.json list, and nothing else is touched."""

    def test_appends_to_a_list_and_leaves_anything_else_alone(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"name": "Example"}], f)
        old = openbq_lanes.EXTRA_APPS
        openbq_lanes.EXTRA_APPS = f.name
        try:
            merged, extended = openbq_lanes._apps(b'[{"name": "BLS"}]')
            self.assertEqual(([a["name"] for a in merged], extended), (["BLS", "Example"], True))
            self.assertEqual(openbq_lanes._apps(b'{"build": 1}'), (None, False))
            openbq_lanes.EXTRA_APPS = f.name + ".absent"
            self.assertEqual(openbq_lanes._apps(b"[]"), ([], False))
        finally:
            openbq_lanes.EXTRA_APPS = old


REPO = Path(__file__).parents[2]
LOGO = REPO / "examples" / "episode3" / "assets" / "bdobb-logo.svg"


def _apps_with(*cards, name="Example"):
    return {"name": name, "tabs": {"t": {"id": "t", "layout": [{"i": c, "x": 0, "y": 0, "w": 4, "h": 4} for c in cards]}}}


class ServableAppsTest(unittest.IsolatedAsyncioTestCase):
    """/apps.json drops every app with a card that /widgets.json does not serve (BDOBB built-ins excepted)."""

    async def asyncSetUp(self):
        self.addCleanup(setattr, openbq_lanes, "EXTRA_APPS", openbq_lanes.EXTRA_APPS)
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)

    async def serve(self, provider_apps, extra_apps, widgets=True):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(extra_apps, f)
        openbq_lanes.EXTRA_APPS = f.name
        self.builds = {"widgets": 0, "apps": 0}
        app = FastAPI()
        if widgets:
            @app.get("/widgets.json")
            async def widgets_json():
                self.builds["widgets"] += 1
                return {"served_widget_obb": {"widgetId": "served_widget_obb"}, "other_obb": {}}

        @app.get("/apps.json")
        async def apps_json():
            self.builds["apps"] += 1
            return provider_apps

        app.middleware("http")(openbq_lanes.middleware)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            first = await client.get("/apps.json")
            again = await client.get("/apps.json")
            listed = await client.get("/widgets.json") if widgets else None
        return first, again, listed

    async def test_apps_with_an_unserved_card_are_dropped_and_logged(self):
        provider = [_apps_with("served_widget_obb", name="Provider"),
                    _apps_with("served_widget_obb", "gone_widget_obb", name="Half provider")]
        extra = [_apps_with("note", "clock", "markdown", "param_echo", name="Built-ins"),
                 _apps_with("served_widget_obb", "note", name="Served example"),
                 _apps_with("videos_video_custom_obb", "note", name="Missing provider")]
        with self.assertLogs("uvicorn.error", "WARNING") as logs:
            first, again, listed = await self.serve(provider, extra)
        names = [a["name"] for a in first.json()]
        self.assertEqual(names, ["Provider", "Built-ins", "Served example"])
        self.assertEqual(again.content, first.content)
        self.assertEqual(int(first.headers["content-length"]), len(first.content))
        self.assertEqual(self.builds, {"widgets": 1, "apps": 1})  # both built once, widgets reused from the cache
        self.assertEqual(listed.json()["served_widget_obb"], {"widgetId": "served_widget_obb"})
        text = "\n".join(logs.output)
        self.assertIn("'Half provider'", text)
        self.assertIn("gone_widget_obb", text)
        self.assertIn("'Missing provider'", text)
        self.assertIn("videos_video_custom_obb", text)
        self.assertNotIn("Served example", text)

    async def test_apps_of_built_ins_only_need_no_widget_catalog(self):
        first, _, _ = await self.serve([], [_apps_with("note", "rss", "website")], widgets=False)
        self.assertEqual([a["name"] for a in first.json()], ["Example"])
        self.assertEqual(self.builds, {"widgets": 0, "apps": 1})

    async def test_without_a_widget_catalog_apps_are_served_unchecked_and_not_cached(self):
        with self.assertLogs("uvicorn.error", "WARNING") as logs:
            first, again, _ = await self.serve([_apps_with("served_widget_obb")], [], widgets=False)
        self.assertIn("/widgets.json unavailable", "\n".join(logs.output))
        self.assertEqual([a["name"] for a in again.json()], ["Example"])
        self.assertEqual(self.builds["apps"], 2)  # retried, not cached


class LogoTest(unittest.IsolatedAsyncioTestCase):
    """The BDOBB logo answers without Basic auth; every other path still asks for it."""

    async def asyncSetUp(self):
        self.addCleanup(setattr, openbq_lanes, "LOGO_FILE", openbq_lanes.LOGO_FILE)
        openbq_lanes.LOGO_FILE = str(LOGO)
        from fastapi import Depends
        from fastapi.security import HTTPBasic

        app = FastAPI()
        basic = HTTPBasic()  # as openbb-api's data routes with OPENBB_API_AUTH=true

        @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"])
        async def protected(path: str, _=Depends(basic)):
            return {"path": path}

        app.add_middleware(CORSMiddleware, allow_origins=["*"])
        app.middleware("http")(openbq_lanes.middleware)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_logo_is_served_without_credentials_as_svg(self):
        r = await self.client.get("/openbq/bdobb-logo.svg", headers={"origin": "http://localhost:4443"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/svg+xml")
        self.assertEqual(r.content, LOGO.read_bytes())
        self.assertEqual(int(r.headers["content-length"]), len(LOGO.read_bytes()))
        self.assertEqual(r.headers.get("access-control-allow-origin"), "*")
        self.assertEqual((await self.client.head("/openbq/bdobb-logo.svg")).status_code, 200)

    async def test_every_other_path_still_needs_credentials(self):
        for path in ["/api/v1/cftc/cot", "/openbq/other.svg", "/openbq/bdobb-logo.svg/x",
                     "/openbq/bdobb-logo.svgz", "/bdobb-logo.svg"]:
            self.assertEqual((await self.client.get(path)).status_code, 401, path)
        self.assertEqual((await self.client.post("/openbq/bdobb-logo.svg")).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/x", auth=("u", "p"))).status_code, 200)

    async def test_a_missing_logo_file_is_a_404(self):
        openbq_lanes.LOGO_FILE = str(LOGO) + ".absent"
        self.assertEqual((await self.client.get("/openbq/bdobb-logo.svg")).status_code, 404)

    def test_the_logo_is_the_svg_bdobb_apps_sync_embeds_and_both_images_copy_it(self):
        import hashlib

        # BDOBB 93bf2633 src/assets/branding/bdobb-app-square.svg; apps-sync.mjs embeds
        # examples/episode3/assets/bdobb-logo.svg as img_dark/img_light.
        self.assertEqual(hashlib.sha256(LOGO.read_bytes()).hexdigest(),
                         "3588fcde88197d2761bf489208a385d234440da9f59174a113bdae96070d3878")
        for dockerfile in sorted(REPO.glob("Dockerfile*")):
            text = dockerfile.read_text()
            if "openbq_lanes.py" in text:
                self.assertIn("COPY examples/episode3/assets/bdobb-logo.svg /workspace/bdobb-logo.svg", text, dockerfile)
                self.assertIn("COPY examples/bdobb/apps.json /workspace/bdobb_apps.json", text, dockerfile)
        self.assertEqual(openbq_lanes.LOGO_PATH, "/openbq/bdobb-logo.svg")


class LaneLogoTest(unittest.IsolatedAsyncioTestCase):
    make = LaneTest.make  # a real lane, without re-running LaneTest's own tests
    asyncTearDown = LaneTest.asyncTearDown

    async def test_with_the_lane_on_the_logo_is_open_and_the_lane_status_is_not(self):
        self.addCleanup(setattr, openbq_lanes, "LOGO_FILE", openbq_lanes.LOGO_FILE)
        openbq_lanes.LOGO_FILE = str(LOGO)
        self.make()
        self.addCleanup(setattr, openbq_lanes, "LANE", openbq_lanes.LANE)
        openbq_lanes.LANE = self.lane  # the module hook, with this test's lane as its own
        old = {k: os.environ.get(k) for k in ("OPENBB_API_AUTH", "OPENBB_API_USERNAME", "OPENBB_API_PASSWORD")}
        os.environ.update(OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p")
        try:
            app = FastAPI()
            app.middleware("http")(openbq_lanes.middleware)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                self.assertEqual((await client.get("/openbq/bdobb-logo.svg")).status_code, 200)
                self.assertEqual((await client.get("/openbq/lanes")).status_code, 401)
                self.assertEqual((await client.get("/openbq/lanes", auth=("u", "p"))).status_code, 200)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)



FIXTURES = REPO / "v5" / "fixtures"
# BDOBB docs/examples/v5-financial-demo/apps.json (release/v5): the V5 Statement Example's one card.
V5_STATEMENT = {"name": "V5 Statement Example", "tabs": {"cash": {"id": "cash", "name": "Cash flow", "layout": [
    {"i": "synthetic_cash_flow", "x": 0, "y": 0, "w": 40, "h": 22, "state": {"params": {}}}]}}}


class FixtureTest(unittest.IsolatedAsyncioTestCase):
    """v5: synthetic_cash_flow is listed in /widgets.json and answers BDOBB's fixture rows."""

    async def asyncSetUp(self):
        for name in ("FIXTURES", "EXTRA_APPS"):
            self.addCleanup(setattr, openbq_lanes, name, getattr(openbq_lanes, name))
        openbq_lanes.FIXTURES = str(FIXTURES)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([V5_STATEMENT], f)
        openbq_lanes.EXTRA_APPS = f.name
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)
        app = FastAPI()

        @app.get("/widgets.json")
        async def widgets_json():
            return {"provider_widget_obb": {"widgetId": "provider_widget_obb"}}

        @app.get("/apps.json")
        async def apps_json():
            return []

        app.middleware("http")(openbq_lanes.middleware)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_the_widget_is_listed_next_to_the_built_ones(self):
        widgets = (await self.client.get("/widgets.json")).json()
        self.assertEqual(sorted(widgets), ["provider_widget_obb", "synthetic_cash_flow"])
        w = widgets["synthetic_cash_flow"]
        self.assertEqual((w["widgetId"], w["name"], w["type"], w["params"]),
                         ("synthetic_cash_flow", "Synthetic Cash Flow", "table", []))
        self.assertEqual(w["endpoint"], "/api/v1/openbq/fixtures/synthetic_cash_flow")

    async def test_the_endpoint_returns_the_expected_rows(self):
        r = await self.client.get("/api/v1/openbq/fixtures/synthetic_cash_flow")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/json")
        self.assertEqual(r.json(), [
            {"fiscal_year": 2026, "fiscal_period": "Q3", "net_cash_from_operating_activities": 12,
             "capital_expenditure": -5},
            {"fiscal_year": 2026, "fiscal_period": "TTM", "net_cash_from_operating_activities": 33,
             "capital_expenditure": -18},
        ])

    async def test_the_v5_statement_example_survives_the_safety_net(self):
        apps = (await self.client.get("/apps.json")).json()
        self.assertEqual([a["name"] for a in apps], ["V5 Statement Example"])

    async def test_unknown_fixtures_are_404_and_auth_is_the_apis(self):
        for path in ["/api/v1/openbq/fixtures/nope", "/api/v1/openbq/fixtures/../widgets", "/api/v1/openbq/fixtures/widgets"]:
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
        old = {k: os.environ.get(k) for k in ("OPENBB_API_AUTH", "OPENBB_API_USERNAME", "OPENBB_API_PASSWORD")}
        os.environ.update(OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p")
        try:
            path = "/api/v1/openbq/fixtures/synthetic_cash_flow"
            self.assertEqual((await self.client.get(path)).status_code, 401)
            self.assertEqual((await self.client.get(path, auth=("u", "p"))).status_code, 200)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_the_vendored_rows_are_bdobbs_cash_flow_json(self):
        import hashlib

        # git blob a2d6e419 of BDOBB docs/examples/v5-financial-demo/cash-flow.json
        data = (FIXTURES / "synthetic_cash_flow.json").read_bytes()
        self.assertEqual(hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(),
                         "a2d6e419eadb2bcc1fc12ea1d7e9c59c4842b780")


if __name__ == "__main__":
    unittest.main()
