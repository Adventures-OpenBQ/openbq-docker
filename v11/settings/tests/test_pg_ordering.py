"""Real PostgreSQL ordering through private ASGI handlers and independent pools.

Supply explicit isolated OPENBQ_TEST_SETTINGS_DSN and
OPENBQ_TEST_SETTINGS_MIGRATION_DSN; never use a live settings database.
"""
import asyncio
import os
import unittest
import uuid

from starlette.requests import Request
from openbq_settings_pg import Runtime
from openbq_settings_pg.config import Config
from openbq_settings_pg.private_state import handle
from openbq_settings_pg.store import Store, migrate

WRITER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
TOKEN = "synthetic_state_fixture_token_123456"
PREFIX = "/_openbq/settings/v1/state/"


@unittest.skipUnless(os.environ.get("OPENBQ_TEST_SETTINGS_DSN"), "requires an isolated PostgreSQL fixture")
class PostgreSQLOrdering(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        migrate(os.environ["OPENBQ_TEST_SETTINGS_MIGRATION_DSN"])

    async def asyncSetUp(self):
        self.principal = "91" + str(uuid.uuid4().int % 10**14).zfill(14)
        config = Config(os.environ["OPENBQ_TEST_SETTINGS_DSN"],
                        "aaaaaaaa-1111-4111-8111-111111111111", True, TOKEN)
        self.stores = [Store(config), Store(config)]
        for store in self.stores:
            await asyncio.to_thread(store.verify)
        self.runtimes = list(map(Runtime, self.stores))

    async def asyncTearDown(self):
        for store in self.stores:
            await asyncio.to_thread(store.close)

    async def call(self, principal, method="PUT", body=b"{}", sequence=None,
                   writer=WRITER, name="settings.json", peer=0, gate=None, receiving=None):
        path = PREFIX + principal + ("/" + name if name else "")
        headers = [(b"authorization", ("Bearer " + TOKEN).encode())]
        if method == "PUT":
            headers.extend(((b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())))
        if sequence is not None:
            headers.extend(((b"x-bdobb-state-writer", writer.encode()),
                            (b"x-bdobb-state-sequence", str(sequence).encode())))

        async def receive():
            if receiving:
                receiving.set()
            if gate:
                await gate.wait()
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": method, "path": path,
                           "raw_path": path.encode(), "query_string": b"", "headers": headers}, receive)
        return await handle(request, self.runtimes[peer])

    async def test_a_held_older_body_cannot_overwrite_a_newer_commit_from_another_pool(self):
        gate, receiving = asyncio.Event(), asyncio.Event()
        old = asyncio.create_task(self.call(self.principal, body=b'{"old":true}', sequence=1,
                                            gate=gate, receiving=receiving))
        await receiving.wait()
        try:
            newer = await self.call(self.principal, body=b'{"new":true}', sequence=2, peer=1)
        finally:
            gate.set()
        late = await old
        self.assertEqual((newer.status_code, late.status_code), (204, 409))
        self.assertEqual(await asyncio.to_thread(self.stores[1].files, self.principal),
                         {"settings.json": '{"new":true}'})
        self.assertEqual(newer.headers.get("x-bdobb-state-writer"), WRITER)
        self.assertEqual(newer.headers.get("x-bdobb-state-sequence"), "2")

    async def test_exact_retries_conflicting_reuse_other_writers_and_restarts(self):
        self.assertEqual((await self.call(self.principal, body=b'{"a":1}', sequence=2)).status_code, 204)
        self.assertEqual((await self.call(self.principal, body=b'{"a":1}', sequence=2, peer=1)).status_code, 204)
        self.assertEqual((await self.call(self.principal, body=b'{"a":2}', sequence=2)).status_code, 409)
        self.assertEqual((await self.call(self.principal, body=b'{"other":true}', sequence=1, writer=OTHER)).status_code, 204)
        await asyncio.to_thread(self.stores[1].close)
        self.stores[1] = Store(self.stores[0].config)
        self.runtimes[1] = Runtime(self.stores[1])
        self.assertEqual((await self.call(self.principal, sequence=1, peer=1)).status_code, 409)

    async def test_versioned_delete_retains_its_fence_and_legacy_cannot_resurrect_it(self):
        self.assertEqual((await self.call(self.principal, body=b'{"old":true}', sequence=1)).status_code, 204)
        self.assertEqual((await self.call(self.principal, method="DELETE", sequence=2)).status_code, 204)
        self.assertEqual((await self.call(self.principal, body=b'{"old":true}', sequence=1, peer=1)).status_code, 409)
        self.assertEqual((await self.call(self.principal, body=b'{}')).status_code, 409)
        self.assertEqual((await self.call(self.principal, method="DELETE", sequence=2)).status_code, 204)
        self.assertEqual(await asyncio.to_thread(self.stores[0].files, self.principal), {})

    async def test_raw_bytes_text_identity_and_workspace_paths_preserve_main_contract(self):
        raw = b' {"x":1,"x":2,"text":"\xff"} '
        self.assertEqual((await self.call("000" + self.principal, body=raw, sequence=1, name="workspaces/a.json")).status_code, 204)
        self.assertEqual((await self.call("000" + self.principal, body=b'{}', sequence=1, name="layouts/a.json")).status_code, 204)
        self.assertEqual(await asyncio.to_thread(self.stores[1].files, self.principal), {})
        files = await asyncio.to_thread(self.stores[1].files, "000" + self.principal)
        self.assertEqual(files["workspaces/a.json"], raw.decode("utf-8", errors="replace"))
        self.assertEqual(files["layouts/a.json"], "{}")

    async def test_refused_quota_does_not_consume_the_retry_sequence(self):
        large = b'"' + b'x' * 262142 + b'"'
        for index in range(8):
            self.assertEqual((await self.call(self.principal, body=large, name=f"dashboards/d{index}.json")).status_code, 204)
        self.assertEqual((await self.call(self.principal, sequence=1)).status_code, 413)
        self.assertEqual((await self.call(self.principal, body=b'{}', name="dashboards/d0.json")).status_code, 204)
        self.assertEqual((await self.call(self.principal, sequence=1)).status_code, 204)


if __name__ == "__main__":
    unittest.main()
