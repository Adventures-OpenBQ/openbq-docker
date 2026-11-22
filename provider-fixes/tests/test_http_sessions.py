# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""HTTP settings must preserve TLS verification and request session ownership."""
import os
import ssl
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
