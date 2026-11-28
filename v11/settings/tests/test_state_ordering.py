"""Wire contracts for versioned browser saves at the real private ASGI boundary."""
import unittest
from types import SimpleNamespace

from starlette.requests import Request
from openbq_settings_pg.private_state import handle

TOKEN = "synthetic_state_fixture_token_123456"
WRITER = "11111111-1111-4111-8111-111111111111"
WRITER_HEADER = "x-bdobb-state-writer"
SEQUENCE_HEADER = "x-bdobb-state-sequence"


class RecordingStorage:
    """Storage is injected here; durable transactions have separate real-PG tests."""
    config = SimpleNamespace(gateway=True, token=TOKEN)

    def __init__(self, status=204):
        self.calls = []
        self.status = status

    def state(self, principal, name, body, version=None):
        self.calls.append((principal, name, body, version))
        return self.status


class Runtime:
    def __init__(self, status=204):
        self.store = RecordingStorage(status)

    async def run(self, operation, *args):
        return operation(*args)


async def call(headers=(), method="PUT", name="settings.json", body=b' {"x":1,"x":2} ', runtime=None):
    runtime = runtime or Runtime()
    path = "/_openbq/settings/v1/state/00042/" + name
    raw_headers = [(b"authorization", ("Bearer " + TOKEN).encode())]
    if method == "PUT":
        raw_headers.extend(((b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())))
    raw_headers.extend((key.encode(), value.encode()) for key, value in headers)
    request = Request({"type": "http", "method": method, "path": path, "raw_path": path.encode(),
                       "query_string": b"", "headers": raw_headers},
                      lambda: receive(body))
    return await handle(request, runtime), runtime


async def receive(body):
    return {"type": "http.request", "body": body, "more_body": False}


class StateOrdering(unittest.IsolatedAsyncioTestCase):
    async def test_committed_version_is_forwarded_and_acknowledged_without_changing_raw_json(self):
        response, runtime = await call(((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "2")))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get(WRITER_HEADER), WRITER)
        self.assertEqual(response.headers.get(SEQUENCE_HEADER), "2")
        principal, name, body, version = runtime.store.calls[0]
        self.assertEqual((principal, name, body), ("00042", "settings.json", b' {"x":1,"x":2} '))
        self.assertEqual((version.writer, version.sequence), (WRITER, 2))

    async def test_malformed_or_duplicate_fence_never_reaches_storage(self):
        cases = [((WRITER_HEADER, WRITER),), ((SEQUENCE_HEADER, "1"),),
                 ((WRITER_HEADER, "invalid"), (SEQUENCE_HEADER, "1")),
                 ((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "0")),
                 ((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "01")),
                 ((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "9007199254740992")),
                 ((WRITER_HEADER, WRITER), (WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "1")),
                 ((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "1"), (SEQUENCE_HEADER, "1"))]
        for headers in cases:
            with self.subTest(headers=headers):
                response, runtime = await call(headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(runtime.store.calls, [])

    async def test_all_saved_dashboard_workspace_and_layout_paths_keep_the_gateway_contract(self):
        for name in ("dashboards/a.json", "workspaces/a.json", "layouts/a.json"):
            with self.subTest(name=name):
                response, _ = await call(((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "1")), name=name)
                self.assertEqual(response.status_code, 204)

    async def test_refused_commit_never_gets_a_success_acknowledgement(self):
        response, runtime = await call(((WRITER_HEADER, WRITER), (SEQUENCE_HEADER, "3")),
                                       method="DELETE", body=b"", runtime=Runtime(409))
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(response.headers.get(WRITER_HEADER))
        self.assertIsNone(runtime.store.calls[0][2])


if __name__ == "__main__":
    unittest.main()
