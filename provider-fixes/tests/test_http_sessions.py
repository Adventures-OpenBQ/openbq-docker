# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""HTTP settings must preserve TLS verification and request session ownership."""
import os
import ssl
import unittest
import gc
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession


class ProxyTls(unittest.IsolatedAsyncioTestCase):
    async def connector_ssl(self, settings):
        from openbb_core.provider.utils import helpers

        with patch.object(helpers, "get_python_request_settings", return_value=settings), patch.dict(
            os.environ, {}, clear=True
        ):
            session = await helpers.get_async_requests_session()
        try:
            return session.connector._ssl
        finally:
            await session.close()

    async def test_proxy_preserves_default_certificate_verification(self):
        self.assertIsNot(await self.connector_ssl({"proxy": "http://proxy.example:8080"}), False)

    async def test_proxy_preserves_explicit_certificate_verification(self):
        self.assertIsNot(
            await self.connector_ssl({"proxy": "http://proxy.example:8080", "verify_ssl": True}), False
        )

    async def test_proxy_preserves_custom_ca_validation(self):
        import certifi

        context = await self.connector_ssl({"proxy": "http://proxy.example:8080", "cafile": certifi.where()})
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    async def test_explicit_verification_opt_out_remains_supported(self):
        self.assertIs(
            await self.connector_ssl({"proxy": "http://proxy.example:8080", "verify_ssl": False}), False
        )


class SessionLifetime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from openbb_core.provider.utils import helpers

        self.helpers = helpers
        self.factory = helpers.get_async_requests_session
        self.settings = patch.object(helpers, "get_python_request_settings", return_value={})
        self.settings.start()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.sessions = []

    async def asyncTearDown(self):
        for session in self.sessions:
            await session.close()
        self.settings.stop()
        self.environment.stop()

    async def track_session(self, **kwargs):
        session = await self.factory(**kwargs)
        self.sessions.append(session)
        return session

    async def test_supplied_single_session_has_no_extra_allocation_and_remains_open(self):
        session = ClientSession()
        self.sessions.append(session)
        response = SimpleNamespace(json=AsyncMock(return_value={"value": 7}))
        with patch.object(self.helpers, "get_async_requests_session", self.track_session), patch.object(
            session, "request", AsyncMock(return_value=response)
        ):
            result = await self.helpers.amake_request("https://example.com/data", session=session)
        self.assertEqual(result, {"value": 7})
        self.assertFalse(session.closed)
        self.assertEqual(len({id(item) for item in self.sessions}), 1, "A caller-owned request allocated an unused session")

    async def test_supplied_batch_session_has_no_extra_allocation_and_keeps_batch_close(self):
        session = ClientSession()
        self.sessions.append(session)
        response = SimpleNamespace(json=AsyncMock(return_value={"value": 7}))
        with patch.object(self.helpers, "get_async_requests_session", self.track_session), patch.object(
            session, "request", AsyncMock(return_value=response)
        ):
            result = await self.helpers.amake_requests(["https://example.com/data"], session=session)
        self.assertEqual(result, [{"value": 7}])
        self.assertTrue(session.closed)
        self.assertEqual(len({id(item) for item in self.sessions}), 1, "A batch allocated unused sessions")

    async def test_explicit_single_session_close_is_preserved(self):
        session = await self.track_session()
        response = SimpleNamespace(json=AsyncMock(return_value={"value": 7}))
        with patch.object(self.helpers, "get_async_requests_session", self.track_session), patch.object(
            session, "request", AsyncMock(return_value=response)
        ):
            result = await self.helpers.amake_request(
                "https://example.com/data", session=session, with_session=False
            )
        self.assertEqual(result, {"value": 7})
        self.assertTrue(session.closed)

    async def test_closed_sessions_are_collectible_during_process_lifetime(self):
        references = []
        for _ in range(4):
            session = await self.factory()
            references.append(weakref.ref(session))
            await session.close()
            del session
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))

    async def test_owned_request_session_closes_when_transport_raises(self):
        async def failed_session(**kwargs):
            session = await self.track_session(**kwargs)
            session.request = AsyncMock(side_effect=TimeoutError("synthetic transport timeout"))
            return session

        with patch.object(self.helpers, "get_async_requests_session", failed_session):
            with self.assertRaises(TimeoutError):
                await self.helpers.amake_request("https://example.com/data")
        self.assertEqual(len(self.sessions), 1)
        self.assertTrue(self.sessions[0].closed)


if __name__ == "__main__":
    unittest.main()
