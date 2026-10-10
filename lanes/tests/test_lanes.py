# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""D8 worker lane: heavy routes run in a child process the API can kill."""
import asyncio
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
            return {"build": self.builds}

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
        self.assertEqual((b.json(), self.builds), ({"build": 1}, 1))

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


if __name__ == "__main__":
    unittest.main()
