"""Offline FRED regressions: real amake_request, loopback HTTP, and diskcache.

Removing rejection/eviction of error responses breaks recovery. Removing either
cache tier breaks cold/warm tests. Removing singleflight or throttling breaks
concurrency/timing tests. All keys and payloads here are synthetic.
"""
import asyncio
import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_fred.utils import api, cache, rate_limiter as limiter

URL = "https://api.stlouisfed.org/fred/series/observations?series_id=IORB&api_key=offline-fixture&file_type=json"
VALID = {"realtime_start": "2024-01-01", "realtime_end": "2024-01-31",
         "observation_start": "2024-01-01", "observation_end": "2024-01-31",
         "units": "lin", "output_type": 1, "file_type": "json", "order_by": "observation_date",
         "sort_order": "asc", "count": 1, "offset": 0, "limit": 100000,
         "observations": [{"realtime_start": "2024-01-01", "realtime_end": "2024-01-31",
                           "date": "2024-01-01", "value": "5.4"}]}
ERROR = {"error_code": 500, "error_message": "Internal Server Error"}
AUTH = {"error_code": 400, "error_message": "Bad Request. The value for api_key is not registered."}


class RoutedSession:
    """Only reroute the external service; keep aiohttp and amake_request real."""
    def __init__(self, origin):
        self.origin = origin
        self.session = aiohttp.ClientSession()

    async def request(self, method, url, **kwargs):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        return await self.session.request(method, self.origin + parsed.path + "?" + parsed.query, **kwargs)

    async def close(self):
        await self.session.close()


class FredCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "OPENBB_FRED_DISK_CACHE": "1",
            "OPENBB_FRED_DISK_CACHE_DIR": str(Path(self.temp.name) / "cache"),
        })
        self.env.start()
        cache.close()
        limiter.cache_clear()
        limiter._last_request_at = 0
        self.responses = []
        self.calls = []
        self.delay = 0
        app = web.Application()
        app.router.add_get("/fred/{tail:.*}", self.serve)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.origin = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])

        async def session_factory(**kwargs):
            return RoutedSession(self.origin)
        self.patches = [
            patch("openbb_core.provider.utils.helpers.get_async_requests_session", session_factory),
            patch.object(limiter, "MIN_INTERVAL_SECONDS", 0.002),
            patch.object(limiter, "DEFAULT_BACKOFF_SECONDS", 0.002),
            patch.object(limiter, "MAX_BACKOFF_SECONDS", 0.002),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        cache.close()
        limiter.cache_clear()
        await self.runner.cleanup()
        self.env.stop()
        self.temp.cleanup()

    async def serve(self, request):
        self.calls.append(time.monotonic())
        if self.delay:
            await asyncio.sleep(self.delay)
        if not self.responses:
            return web.json_response({"error_code": 500, "error_message": "Fixture exhausted"}, status=500)
        status, payload = self.responses.pop(0)
        return web.json_response(payload, status=status, headers={"Retry-After": "0"} if status == 429 else None)

    async def observations(self, **kwargs):
        return await api.get_observations("IORB", "offline-fixture", **kwargs)

    async def test_default_cold_memory_warm_and_disk_warm_preserve_valid_data(self):
        self.responses = [(200, copy.deepcopy(VALID))]
        first = await self.observations()
        self.assertEqual(first[0]["value"], "5.4")
        first[0]["value"] = "mutated consumer copy"
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(cache.stats()["items"], 1)
        limiter.cache_clear()
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 1)
        _, expires = cache.get_disk_cache().get(cache.redact(URL), expire_time=True)
        self.assertGreater(expires - time.time(), 14390)

    async def test_transient_http_error_is_surfaced_never_cached_then_recovers(self):
        self.responses = [(500, ERROR), (200, VALID)]
        with self.assertRaisesRegex(Exception, "500|Internal Server Error"):
            await self.observations()
        self.assertEqual(cache.stats()["items"], 0)
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 2)

    async def test_error_envelope_with_http_200_is_never_cached_then_recovers(self):
        self.responses = [(200, ERROR), (200, VALID)]
        with self.assertRaisesRegex(OpenBBError, "Internal Server Error"):
            await self.observations()
        self.assertEqual(cache.stats()["items"], 0)
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 2)

    async def test_legacy_disk_error_is_evicted_and_refetched_without_waiting_ttl(self):
        await cache.disk_set(URL, ERROR)
        cache.close()
        self.responses = [(200, VALID)]
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(await cache.disk_get(URL), VALID)
        self.assertEqual(len(self.calls), 1)

    async def test_legacy_poison_stays_evicted_when_refetch_also_fails(self):
        await cache.disk_set(URL, ERROR)
        self.responses = [(500, ERROR), (200, VALID)]
        with self.assertRaisesRegex(Exception, "500|Internal Server Error"):
            await self.observations()
        self.assertIsNone(await cache.disk_get(URL))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 2)

    async def test_legacy_error_envelope_variants_are_evicted_and_refetched(self):
        variants = [
            {"error_code": "500"},
            {"error_message": "Internal Server Error"},
            {"status_code": "503", "message": "Service unavailable"},
            {"status_code": 401, "message": "Unauthorized"},
        ]
        for payload in variants:
            with self.subTest(payload=payload):
                limiter.cache_clear()
                await cache.disk_set(URL, payload)
                self.responses = [(200, VALID)]
                self.assertEqual((await self.observations())[0]["value"], "5.4")
                self.assertEqual(await cache.disk_get(URL), VALID)
        self.assertEqual(len(self.calls), 4)

    async def test_legacy_memory_error_is_evicted_and_refetched(self):
        limiter._cache_set(limiter._cache_key(URL), ERROR)
        self.responses = [(200, VALID)]
        self.assertEqual((await self.observations())[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 1)

    async def test_auth_error_is_surfaced_every_time_without_cache_or_retry(self):
        self.responses = [(400, AUTH), (400, AUTH)]
        for count in (1, 2):
            with self.assertRaisesRegex(Exception, "400|not registered") as caught:
                await self.observations()
            self.assertNotIn("offline-fixture", str(caught.exception))
            self.assertEqual(len(self.calls), count)
            self.assertEqual(cache.stats()["items"], 0)

    async def test_http_error_payload_semantics_are_preserved_without_caching(self):
        self.responses = [(503, {"detail": "Service unavailable"}), (200, VALID)]
        self.assertEqual(await limiter.fred_get(URL), {"detail": "Service unavailable"})
        self.assertEqual(cache.stats()["items"], 0)
        self.assertEqual(await limiter.fred_get(URL), VALID)

    async def test_429_keeps_bounded_retry_and_valid_result_caching(self):
        self.responses = [(429, {"error_code": 429, "error_message": "Too Many Requests"}), (200, VALID)]
        self.assertEqual(await limiter.fred_get(URL, max_retries=1), VALID)
        self.assertEqual(await limiter.fred_get(URL), VALID)
        self.assertEqual(len(self.calls), 2)

    async def test_exhausted_429_is_not_cached_and_next_request_recovers(self):
        self.responses = [(429, {"error_code": 429, "error_message": "Too Many Requests"}), (200, VALID)]
        with self.assertRaisesRegex(OpenBBError, "429"):
            await limiter.fred_get(URL, max_retries=0)
        self.assertEqual(cache.stats()["items"], 0)
        self.assertEqual(await limiter.fred_get(URL), VALID)
        self.assertEqual(len(self.calls), 2)

    async def test_use_cache_false_bypasses_legacy_poison_and_does_not_write(self):
        await cache.disk_set(URL, ERROR)
        self.responses = [(200, VALID), (200, VALID)]
        self.assertEqual((await self.observations(use_cache=False))[0]["value"], "5.4")
        self.assertEqual((await self.observations(use_cache=False))[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(await cache.disk_get(URL), ERROR)

    async def test_singleflight_preserves_independent_consumer_copies(self):
        self.responses = [(200, VALID)]
        self.delay = 0.03
        results = await asyncio.gather(*(limiter.fred_get(URL) for _ in range(6)))
        self.assertEqual(len(self.calls), 1)
        results[0]["observations"][0]["value"] = "changed"
        for result in results[1:]:
            self.assertEqual(result["observations"][0]["value"], "5.4")

    async def test_custom_callback_success_and_warm_cache_keep_transformed_result(self):
        self.responses = [(200, VALID)]
        async def callback(response, session):
            self.assertEqual(response.status, 200)
            self.assertIsInstance(session, RoutedSession)
            return (await response.json())["observations"]
        self.assertEqual((await limiter.fred_get(URL, response_callback=callback))[0]["value"], "5.4")
        self.assertEqual((await limiter.fred_get(URL, response_callback=callback))[0]["value"], "5.4")
        self.assertEqual(len(self.calls), 1)

    async def test_http_error_callback_keeps_its_result_but_cannot_fill_caches(self):
        self.responses = [(500, ERROR), (200, VALID)]
        statuses = []
        async def callback(response, session):
            statuses.append(response.status)
            return {"observations": [{"date": "2024-01-01", "value": "5.4"}]}
        self.assertEqual((await limiter.fred_get(URL, response_callback=callback))["observations"][0]["value"], "5.4")
        self.assertEqual(cache.stats()["items"], 0)
        self.assertEqual((await limiter.fred_get(URL, response_callback=callback))["observations"][0]["value"], "5.4")
        self.assertEqual(statuses, [500, 200])

    async def test_uncached_requests_still_respect_global_minimum_interval(self):
        self.responses = [(200, VALID)] * 3
        with patch.object(limiter, "MIN_INTERVAL_SECONDS", 0.04):
            await asyncio.gather(*(limiter.fred_get(URL, use_cache=False) for _ in range(3)))
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(b - a >= 0.025 for a, b in zip(self.calls, self.calls[1:])), self.calls)

if __name__ == "__main__":
    unittest.main(verbosity=2)
