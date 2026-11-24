"""Shared FRED requests must finish independently of other callers' lifecycle."""
import asyncio
import copy
import unittest
from unittest.mock import patch

from openbb_fred.utils import cache, rate_limiter as limiter

URL = "https://api.stlouisfed.org/fred/series/observations?series_id=IORB&api_key=offline-fixture"
VALID = {"observations": [{"date": "2024-01-01", "value": "5.4"}]}


class SingleflightLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        limiter.cache_clear()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.tasks = []

        async def missing(url):
            return None

        async def fetch(*args, **kwargs):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return copy.deepcopy(VALID)

        async def store(url, result):
            return None

        self.enterContext(patch.object(cache, "disk_get", missing))
        self.enterContext(patch.object(cache, "disk_set", store))
        self.enterContext(patch.object(limiter, "_fetch", fetch))

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        limiter.cache_clear()

    def task(self, coroutine=None):
        task = asyncio.create_task(coroutine if coroutine is not None else limiter.fred_get(URL))
        self.tasks.append(task)
        return task

    async def test_cancelling_one_waiter_preserves_owner_and_other_waiter(self):
        owner = self.task()
        await self.started.wait()
        cancelled, other = self.task(), self.task()
        await asyncio.sleep(0)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        self.release.set()
        results = await asyncio.gather(owner, other, return_exceptions=True)
        self.assertEqual(results, [VALID, VALID])
        self.assertEqual(self.calls, 1)
        self.assertFalse(limiter._inflight)

    async def test_disk_write_error_finishes_all_waiters_and_allows_recovery(self):
        async def broken_store(url, result):
            raise OSError("synthetic disk full")

        self.enterContext(patch.object(cache, "disk_set", broken_store))
        owner = self.task()
        await self.started.wait()
        joined = self.task()
        await asyncio.sleep(0)
        self.release.set()
        results = await asyncio.wait_for(asyncio.gather(owner, joined, return_exceptions=True), 0.5)
        self.assertTrue(all(isinstance(result, OSError) for result in results), results)
        self.assertFalse(limiter._inflight)
        self.assertEqual(await limiter.fred_get(URL), VALID)

    async def test_owner_cancellation_during_cache_write_finishes_waiter(self):
        storing = asyncio.Event()

        async def blocked_store(url, result):
            storing.set()
            await asyncio.Event().wait()

        self.enterContext(patch.object(cache, "disk_set", blocked_store))
        owner = self.task()
        await self.started.wait()
        joined = self.task()
        await asyncio.sleep(0)
        self.release.set()
        await storing.wait()
        owner.cancel()
        results = await asyncio.wait_for(asyncio.gather(owner, joined, return_exceptions=True), 0.5)
        self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results), results)
        self.assertFalse(limiter._inflight)

    async def test_owner_mutation_cannot_change_another_waiters_result(self):
        async def consume_owner():
            result = await limiter.fred_get(URL)
            result["observations"][0]["value"] = "owner mutation"
            return result

        owner = self.task(consume_owner())
        await self.started.wait()
        joined = self.task()
        await asyncio.sleep(0)
        self.release.set()
        await asyncio.gather(owner, joined)
        self.assertEqual(joined.result(), VALID)
        self.assertEqual(await limiter.fred_get(URL), VALID)


if __name__ == "__main__":
    unittest.main()
