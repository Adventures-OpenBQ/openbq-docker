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
from unittest import mock
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

os.environ["OPENBQ_ROLE"] = "worker"  # importing the module must not spawn the production lane
os.environ["OPENBQ_EXTRA_APPS"] = "/nonexistent/bdobb_apps.json"  # tests set their own extras
sys.path.insert(0, str(Path(__file__).parents[1]))
import openbq_lanes  # noqa: E402

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

    async def test_a_cached_catalog_still_follows_basic_auth(self):
        openbq_lanes._CATALOG_CACHE.clear()
        self.addCleanup(openbq_lanes._CATALOG_CACHE.clear)
        app = FastAPI()

        @app.get("/widgets.json")
        async def widgets(request: Request):
            if not request.headers.get("authorization"):  # the API's Basic auth dependency
                return JSONResponse({"detail": "Unauthorized"}, 401)
            return {"w": {"name": "x"}}

        app.middleware("http")(openbq_lanes.middleware)
        with mock.patch.dict(os.environ, OPENBB_API_AUTH="true", OPENBB_API_USERNAME="u", OPENBB_API_PASSWORD="p"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                self.assertEqual((await client.get("/widgets.json", auth=("u", "p"))).status_code, 200)
                anon = await client.get("/widgets.json")
                wrong = await client.get("/widgets.json", auth=("u", "x"))
        self.assertEqual((anon.status_code, wrong.status_code), (401, 401))
        self.assertEqual(anon.headers.get("www-authenticate"), "Basic")

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


if __name__ == "__main__":
    unittest.main()


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

