# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Offline transport and scheduler checks for the seven raw BLS PDF routes."""
import asyncio
import base64
import importlib
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from requests import Response


PDF = b"%PDF-1.4\nBLS document transport fixture\n%%EOF\n"
ROUTES = (
    ("ces", "employment_situation"),
    ("cpi", "cpi"),
    ("ppi", "ppi"),
    ("productivity", "productivity"),
    ("jolts", "jolts"),
    ("realer", "real_earnings"),
    ("ximpim", "import_export"),
)


def response(body=PDF, status=200):
    result = Response()
    result.status_code = status
    result._content = body
    return result


class BlsDocumentSafety(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.modules = []
        for name, path in ROUTES:
            module = importlib.import_module(f"openbb_bls.routers.{name}")
            cls.modules.append(module)
            cls.app.include_router(module.router.api_router, prefix="/api/v1/bls")

    async def post(self, path, urls):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            result = await client.post(
                f"/api/v1/bls/{path}/document_download", json={"url": urls}
            )
        self.assertEqual(result.status_code, 200)
        return result.json()

    async def test_upstream_failures_are_per_file_errors_without_pdf_payloads(self):
        for _, path in ROUTES:
            for body, status in (
                (b"<html>Source denial marker</html>", 200),
                (PDF, 403),
                (PDF, 302),
                (b"%PDF-1.4\ntruncated", 200),
                (b"%PDF-1.4\n%%EOF" + b"x" * 2048, 200),
                (b"prefix\n" + PDF, 200),
            ):
                with self.subTest(path=path, status=status, body=body[:30]), patch(
                    "openbb_core.provider.utils.helpers.make_request",
                    return_value=response(body, status),
                ):
                    result = (await self.post(path, "https://www.bls.gov/release.pdf"))[0]
                    self.assertEqual(result.get("error_type"), "download_error")
                    self.assertNotIn("data_format", result)
                    self.assertNotIn("Source denial marker", result["content"])

    async def test_complete_pdfs_keep_both_public_hosts_and_standard_https_port(self):
        for _, path in ROUTES:
            for host, status, body in (
                ("www.bls.gov", 200, PDF),
                ("bls.gov", 206, PDF),
                ("www.bls.gov:443", 200, PDF),
                ("bls.gov", 200, PDF + b" " * 2042),
            ):
                with self.subTest(path=path, host=host), patch(
                    "openbb_core.provider.utils.helpers.make_request",
                    return_value=response(body, status),
                ) as request:
                    result = (await self.post(path, f"https://{host}/release.pdf"))[0]
                    self.assertEqual(base64.b64decode(result["content"], validate=True), body)
                    self.assertEqual(result["data_format"], {"data_type": "pdf", "filename": "release.pdf"})
                    self.assertIs(request.call_args.kwargs.get("allow_redirects"), False)
                    self.assertTrue(request.call_args.kwargs["headers"]["Accept"].startswith("application/pdf"))

    async def test_untrusted_urls_never_reach_transport(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        for module in self.modules:
            for url in (
                "http://127.0.0.1/private.pdf?bls.gov",
                "http://www.bls.gov/release.pdf",
                "https://www.bls.gov.example.com/release.pdf",
                "https://www.bls.gov./release.pdf",
                "https://user:password@www.bls.gov/release.pdf",
                "https://user@bls.gov/release.pdf",
                "https://www.bls.gov:8443/release.pdf",
                "https://www.bls.gov:invalid/release.pdf",
                "https://www.bls.gov/release.txt",
            ):
                with self.subTest(module=module.__name__, url=url), patch(
                    "openbb_core.provider.utils.helpers.make_request", return_value=response()
                ) as request:
                    with self.assertRaises((OpenBBError, ValueError)):
                        await module.document_download({"url": url})
                    request.assert_not_called()

    async def test_a_failed_file_does_not_discard_the_next_pdf(self):
        for _, path in ROUTES:
            with self.subTest(path=path), patch(
                "openbb_core.provider.utils.helpers.make_request",
                side_effect=[response(b"<html>denied</html>"), response()],
            ):
                result = await self.post(path, ["https://bls.gov/first.pdf", "https://bls.gov/second.pdf"])
                self.assertEqual(result[0].get("error_type"), "download_error")
                self.assertEqual(base64.b64decode(result[1]["content"], validate=True), PDF)

    async def test_empty_selection_is_still_empty(self):
        for _, path in ROUTES:
            for urls in (None, []):
                with self.subTest(path=path, urls=urls):
                    self.assertEqual(await self.post(path, urls), [])

    async def test_a_quick_request_runs_while_each_download_is_waiting(self):
        for _, path in ROUTES:
            started, finished, release = threading.Event(), threading.Event(), threading.Event()

            def download(*args, **kwargs):
                started.set()
                release.wait(1)
                finished.set()
                return response()

            app = FastAPI()
            module = self.modules[[p for _, p in ROUTES].index(path)]
            app.include_router(module.router.api_router, prefix="/api/v1/bls")

            @app.get("/quick")
            async def quick():
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.001)
                waiting = started.is_set() and not finished.is_set()
                release.set()
                return {"download_waiting": waiting}

            with self.subTest(path=path), patch(
                "openbb_core.provider.utils.helpers.make_request", side_effect=download
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    document, heartbeat = await asyncio.gather(
                        client.post(f"/api/v1/bls/{path}/document_download", json={"url": "https://bls.gov/release.pdf"}),
                        client.get("/quick"),
                    )
                self.assertEqual(heartbeat.json(), {"download_waiting": True})
                self.assertEqual(base64.b64decode(document.json()[0]["content"], validate=True), PDF)


if __name__ == "__main__":
    unittest.main()
