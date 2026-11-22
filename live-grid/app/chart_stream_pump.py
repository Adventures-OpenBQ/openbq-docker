"""Chart source boundary. Native calls and conversion stay on the q owner thread."""

import asyncio
from typing import Protocol
from .chart_stream_protocol import cursor_cmp, normalize_view, wire


class ChartSource(Protocol):
    qualified: bool

    async def snapshot(self, view: dict) -> dict: ...
    async def changes(self, cursor: dict, view: dict) -> dict: ...
    async def status(self) -> dict: ...


class OwnerChartSource:
    """rpc(session, operation, args) is called ONLY inside session.run().

    The installed qualified client supplies rpc; no raw-expression fallback exists.
    Qualification/capability gating is the caller's responsibility before construction.
    """

    qualified = True

    def __init__(self, session, rpc):
        self.session, self.rpc = session, rpc

    async def _call(self, operation, *args):
        return await asyncio.to_thread(
            self.session.run, lambda: wire(self.rpc(self.session, operation, list(args)))
        )

    async def snapshot(self, view):
        return await self._call("readChartSnapshot", view)

    async def changes(self, cursor, view):
        return await self._call("readChartChanges", cursor, view)

    async def status(self):
        return await self._call("streamStatus")


class ChartPump:
    def __init__(self, source, view):
        self.source, self.view = source, normalize_view(view)
        self.cursor = None
        self.floor = None

    async def admit(self):
        snapshot = wire(await asyncio.wait_for(self.source.snapshot(self.view), 5))
        self.cursor = snapshot["cursor"]
        self.floor = snapshot["view_floor"]
        self.check_items(snapshot["items"], self.cursor)
        # Retention is inspected before any potentially slow transport send.
        changes = await self.poll()
        return snapshot, changes

    def check_items(self, items, high):
        for item in items:
            tick = self.view["mode"] == "ticks"
            identity = item["tick_id"] if tick else item["revision"]
            if cursor_cmp(identity, high) > 0:
                raise ValueError("item ahead of watermark")
            symbol = item["sym"] if tick else item["key"]["symbol"]
            when = item["time"] if tick else item["key"]["bucket_start"]
            if symbol != self.view["symbol"] or (
                not tick and item["key"]["interval"] != self.view["interval"]
            ):
                raise ValueError("source view mismatch")
            # Candles may start before start when the requested start is mid-bucket.
            if tick and (
                when < self.view["start"] or ("end" in self.view and when >= self.view["end"])
            ):
                raise ValueError("source item outside view")

    async def poll(self):
        changes = wire(await asyncio.wait_for(self.source.changes(self.cursor, self.view), 5))
        if "reason" not in changes:
            if cursor_cmp(changes["from_cursor"], self.cursor) != 0:
                raise ValueError("source returned a cursor hole")
            if cursor_cmp(changes["through_cursor"], self.cursor) < 0:
                raise ValueError("source cursor went backwards")
            unavailable = changes.get("unavailable_buckets", [])
            if self.floor and self.floor.get("kind") == "candle":
                unavailable = [
                    bucket
                    for bucket in unavailable
                    if not isinstance(bucket, dict)
                    or bucket.get("bucket_start", bucket.get("key", {}).get("bucket_start", "~"))
                    >= self.floor["bucket_start"]
                ]
            if unavailable:
                status = wire(await asyncio.wait_for(self.source.status(), 5))
                return {
                    "reason": "coverage_lost",
                    "current_cursor": status["current_cursor"],
                    "coverage": status["coverage"],
                }
            items = (
                [tick for batch in changes["batches"] for tick in batch["ticks"]]
                if self.view["mode"] == "ticks"
                else changes["candles"]
            )
            self.check_items(items, changes["through_cursor"])
            self.cursor = changes["through_cursor"]
        return changes


class StoreChartSource:
    """Monotonic feature admission after an authenticated named-capability handshake."""

    qualified = False
    REQUIRED = {"readChartSnapshot", "readChartChanges", "streamStatus", "chart_stream_v1"}

    def __init__(self, store):
        self.store = store

    async def qualify(self):
        status = await self.status()
        if not self.REQUIRED.issubset(self.store.session.capabilities):
            raise ValueError("chart capabilities unavailable")
        if not isinstance(status.get("clock"), str) or not status.get("current_cursor"):
            raise ValueError("chart status unavailable")
        self.qualified = True
        return status

    async def snapshot(self, view):
        return wire(await asyncio.to_thread(self.store.read_chart_snapshot, view))

    async def changes(self, cursor, view):
        return wire(await asyncio.to_thread(self.store.read_chart_changes, cursor, view))

    async def status(self):
        return wire(await asyncio.to_thread(self.store.stream_status))


class SharedChartSource:
    """Bounded 50 ms normalized-read coalescing across all socket generations.

    Results are immutable to consumers. In-flight reads are shared; cancellation of
    one socket does not cancel another socket's owner-thread read. Completed cache
    references are limited to 8 MiB / 128 entries and expire after one pump interval.
    """

    def __init__(self, source):
        self.source = source
        self.cache = {}
        self.cache_bytes = 0
        self.inflight = {}
        self.slots = asyncio.Semaphore(2)

    def __getattr__(self, name):
        return getattr(self.source, name)

    def _expire(self):
        import time

        now = time.monotonic()
        for key, (until, size, _) in list(self.cache.items()):
            if until <= now:
                del self.cache[key]
                self.cache_bytes -= size

    async def _read(self, operation, args):
        import json
        import time

        self._expire()
        key = (operation, json.dumps(args, sort_keys=True, separators=(",", ":")))
        if key in self.cache:
            return self.cache[key][2]
        task = self.inflight.get(key)
        if task is None:

            async def fetch():
                async with self.slots:
                    result = wire(await asyncio.wait_for(getattr(self.source, operation)(*args), 5))
                size = len(json.dumps(result, separators=(",", ":"), allow_nan=False).encode())
                self._expire()
                if size <= 8 * 1024 * 1024:
                    while self.cache and (
                        len(self.cache) >= 128 or self.cache_bytes + size > 8 * 1024 * 1024
                    ):
                        old = next(iter(self.cache))
                        _, removed, _ = self.cache.pop(old)
                        self.cache_bytes -= removed
                    self.cache[key] = (time.monotonic() + 0.05, size, result)
                    self.cache_bytes += size

                    def expire_entry():
                        entry = self.cache.get(key)
                        if entry and entry[2] is result:
                            self.cache.pop(key)
                            self.cache_bytes -= size

                    asyncio.get_running_loop().call_later(0.05, expire_entry)
                return result

            # Bound distinct queued native work too, rather than merely its output cache.
            if len(self.inflight) >= 64:
                raise ValueError("chart read admission limit")
            task = asyncio.create_task(fetch())
            self.inflight[key] = task

            def finished(done):
                self.inflight.pop(key, None)
                # Retrieve failures even when the final subscriber disconnected.
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def snapshot(self, view):
        return await self._read("snapshot", [normalize_view(view)])

    async def changes(self, cursor, view):
        return await self._read("changes", [cursor, normalize_view(view)])

    async def status(self):
        return await self._read("status", [])

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
        self.cache.clear()
        self.cache_bytes = 0
