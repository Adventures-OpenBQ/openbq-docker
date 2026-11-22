# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Fed document boundaries, complete PDF responses, and responsive raw routes."""
import asyncio
import base64
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

PDF = b"%PDF-1.4\nSynthetic public document\n%%EOF\n"
PUBLIC = "https://www.newyorkfed.org/paper.pdf"
ITEM = "https://fedinprint.org/item/fedawp/1/original"
UNTRUSTED = [
    "http://127.0.0.1/private.pdf",
    "https://127.0.0.1/private.pdf",
    "http://127.0.0.1/fedinprint.org/item/private",
    "https://www.newyorkfed.org.evil.example/paper.pdf",
    "https://www.newyorkfed.org./paper.pdf",
    "https://user:password@www.newyorkfed.org/paper.pdf",
    "https://www.newyorkfed.org:8443/paper.pdf",
    "https://www.newyorkfed.org:invalid/paper.pdf",
]


class Response:
    def __init__(self, body=PDF, status=200, location=None):
        self.content = body
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.text = body.decode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"Upstream HTTP {self.status_code}")


class FedDocuments(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from openbb_federal_reserve import federal_reserve_router as router
        from openbb_federal_reserve import ffiec
        from openbb_federal_reserve.utils import fedinprint
        self.router, self.ffiec, self.fedinprint = router, ffiec, fedinprint

    async def test_fomc_invalid_origin_keeps_its_http_400_contract(self):
        import httpx
        from fastapi import FastAPI
        from openbb_core.api.app_loader import AppLoader

        app = FastAPI()
        AppLoader.add_exception_handlers(app)
        app.include_router(self.router.router.api_router, prefix="/api/v1/federal_reserve")
        with patch("openbb_core.provider.utils.helpers.make_request", side_effect=AssertionError("untrusted transport")):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
                result = await client.post("/api/v1/federal_reserve/fomc_documents_download", json={"url": ["https://invalid.example/document.pdf"]})
        self.assertEqual(result.status_code, 400, result.text)

    def test_nic_rejects_non_success_status_even_with_complete_pdf(self):
        from openbb_federal_reserve.utils import ffiec
        with patch.object(ffiec, "_get_session") as factory:
            factory.return_value.get.return_value = Response(PDF, 302)
            with self.assertRaises(ValueError):
                ffiec._fetch_bytes("Reports/document.pdf")

    def test_nic_warmup_refuses_private_redirect_before_following(self):
        from openbb_federal_reserve.utils import ffiec
        calls = []

        class Session:
            def get(inner, url, **kwargs):
                calls.append((url, kwargs))
                return Response(PDF, 302, "http://127.0.0.1/private.pdf")

        with self.assertRaises(ValueError):
            ffiec._warmup(Session())
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][1].get("allow_redirects"), False)

    def test_nic_follows_only_validated_public_redirects(self):
        from openbb_federal_reserve.utils import ffiec
        calls = []

        class Session:
            def get(inner, url, **kwargs):
                calls.append((url, kwargs))
                return Response(b"", 302, "/npw/Reports/final.pdf") if len(calls) == 1 else Response(PDF)

        with patch.object(ffiec, "_get_session", return_value=Session()):
            self.assertEqual(ffiec._fetch_bytes("Reports/document.pdf"), PDF)
        self.assertEqual([url for url, _ in calls], ["https://www.ffiec.gov/npw/Reports/document.pdf", "https://www.ffiec.gov/npw/Reports/final.pdf"])
        self.assertTrue(all(options.get("allow_redirects") is False for _, options in calls))

    def test_nic_redirects_share_the_existing_request_budget(self):
        from openbb_federal_reserve.utils import ffiec
        elapsed, budgets = [0], []

        class Session:
            def get(inner, url, **kwargs):
                budgets.append(kwargs["timeout"])
                elapsed[0] += 100
                return Response(PDF, 302, "/npw/Reports/next.pdf")

        with patch("time.monotonic", side_effect=lambda: elapsed[0]), patch.object(ffiec, "_get_session", return_value=Session()):
            with self.assertRaises(TimeoutError):
                ffiec._fetch_bytes("Reports/document.pdf")
        self.assertEqual(budgets, [180, 80])

    async def test_untrusted_initial_urls_never_enter_resolver_or_downloader(self):
        def unexpected(*args):
            self.fail("untrusted input reached document transport")
        for url in UNTRUSTED:
            with self.subTest(url=url), patch.object(self.router, "_download_pdf", side_effect=unexpected), patch.object(self.fedinprint, "resolve_file", side_effect=unexpected):
                result = (await self.router.regional_publications_download({"url": [url]}))[0]
                self.assertEqual(result.get("error_type"), "download_error")
                self.assertNotIn("untrusted input reached document transport", result["content"])

    async def test_untrusted_resolver_output_never_enters_downloader(self):
        for target in UNTRUSTED:
            with self.subTest(target=target), patch.object(self.fedinprint, "resolve_file", return_value=target), patch.object(self.router, "_download_pdf", side_effect=AssertionError("unsafe resolved transport")):
                result = (await self.router.regional_publications_download({"url": [ITEM]}))[0]
                self.assertEqual(result.get("error_type"), "download_error")
                self.assertNotIn("unsafe resolved transport", result["content"])

    async def test_trusted_url_containing_fedinprint_in_query_is_not_resolved(self):
        url = PUBLIC + "?next=fedinprint.org/item/foo"
        with patch.object(self.fedinprint, "resolve_file", side_effect=AssertionError("wrong resolver")), patch.object(self.router, "_download_pdf", return_value=PDF):
            result = (await self.router.regional_publications_download({"url": [url]}))[0]
        self.assertIn("data_format", result)
        self.assertEqual(base64.b64decode(result["content"]), PDF)

    async def test_generic_and_all_twelve_registered_district_callers_refuse_private_input(self):
        routers = [self.router.router] + [entry[0] for entry in self.router._REGIONAL_DISTRICTS]
        endpoints = [r.endpoint for router in routers for r in router.api_router.routes if getattr(r, "path", "").endswith("/regional_publications_download")]
        self.assertEqual(len(endpoints), 13)
        with patch.object(self.router, "_download_pdf", return_value=PDF):
            for endpoint in endpoints:
                result = (await endpoint({"url": [UNTRUSTED[0]]}))[0]
                self.assertEqual(result.get("error_type"), "download_error")

    async def test_source_evidenced_public_origins_round_trip(self):
        hosts = ["www.atlantafed.org", "www.bostonfed.org", "www.chicagofed.org", "www.clevelandfed.org", "www.dallasfed.org", "dallasfed.org", "www.kansascityfed.org", "kcresearch-share.kansascityfed.org", "www.minneapolisfed.org", "www.newyorkfed.org", "www.philadelphiafed.org", "www.richmondfed.org", "www.frbsf.org", "www.stlouisfed.org", "fraser.stlouisfed.org"]
        with patch.object(self.router, "_download_pdf", return_value=PDF):
            for host in hosts:
                with self.subTest(host=host):
                    result = (await self.router.regional_publications_download({"url": [f"https://{host}:443/paper.pdf"]}))[0]
                    self.assertEqual(base64.b64decode(result["content"]), PDF)

    def download(self, response, fallback=None):
        class Session:
            def get(inner, url, **kwargs):
                if kwargs.get("allow_redirects") is not False and response.status_code in range(300, 400):
                    return Response(PDF)  # Synthetic implicit redirect: guard must disable it.
                return response
        with patch("openbb_federal_reserve.utils.curl_session.get_session", return_value=Session()), patch("openbb_core.provider.utils.helpers.make_request", return_value=fallback or response):
            return self.router._download_pdf(PUBLIC)

    def test_downloader_rejects_http_html_and_truncated_pdf(self):
        for response in [Response(PDF, 403), Response(b"<html>denied</html>"), Response(b"%PDF-1.4\ntruncated")]:
            with self.subTest(body=response.content, status=response.status_code), self.assertRaises(Exception):
                self.download(response)

    def test_downloader_keeps_browser_failure_fallback_and_valid_bytes(self):
        self.assertEqual(self.download(Response(PDF)), PDF)
        self.assertEqual(self.download(Response(PDF, 403), Response(PDF)), PDF)

    def test_downloader_refuses_private_redirect_before_second_request(self):
        with self.assertRaises(Exception):
            self.download(Response(PDF, 302, "http://127.0.0.1/private.pdf"))

    def test_downloader_follows_only_validated_public_redirects_and_stops_loops(self):
        seen = []
        class Session:
            def get(inner, url, **kwargs):
                seen.append(url)
                if kwargs.get("allow_redirects") is not False:
                    raise AssertionError("unchecked redirect handling")
                return Response(b"", 302, "/final.pdf") if len(seen) == 1 else Response(PDF)
        with patch("openbb_federal_reserve.utils.curl_session.get_session", return_value=Session()), patch("openbb_core.provider.utils.helpers.make_request", side_effect=AssertionError("unexpected fallback")):
            self.assertEqual(self.router._download_pdf(PUBLIC), PDF)
        self.assertEqual(seen, [PUBLIC, "https://www.newyorkfed.org/final.pdf"])
        seen.clear()
        def loop(url, **kwargs):
            seen.append(url)
            if len(seen) > 12:
                raise AssertionError("unbounded redirects")
            return Response(b"", 302, PUBLIC)
        with patch("openbb_federal_reserve.utils.curl_session.get_session") as session, patch("openbb_core.provider.utils.helpers.make_request", side_effect=loop):
            session.return_value.get.side_effect = loop
            with self.assertRaises(Exception) as raised:
                self.router._download_pdf(PUBLIC)
        self.assertNotIn("unbounded redirects", str(raised.exception))
        self.assertLessEqual(len(seen), 12)

    def test_downloader_checks_initial_origin_even_when_called_directly(self):
        for url in UNTRUSTED:
            with self.subTest(url=url), patch("openbb_federal_reserve.utils.curl_session.get_session", side_effect=AssertionError("unsafe transport")), patch("openbb_core.provider.utils.helpers.make_request", side_effect=AssertionError("unsafe transport")):
                try:
                    self.router._download_pdf(url)
                except Exception as exc:
                    self.assertNotIn("unsafe transport", str(exc))
                else:
                    self.fail("unsafe initial URL accepted")

    def test_resolver_fetch_refuses_untrusted_origin_before_session(self):
        for url in UNTRUSTED:
            with self.subTest(url=url), patch.object(self.fedinprint, "_get_session", side_effect=AssertionError("unsafe resolver transport")):
                with self.assertRaises(Exception) as raised:
                    self.fedinprint.fetch_text(url)
                self.assertNotIn("unsafe resolver transport", str(raised.exception))

    def test_doi_and_fraser_intermediates_keep_validated_redirects(self):
        pages = {
            ITEM: Response(b'<meta name="citation_doi" content="10.29338/wp2026-19">'),
            "https://doi.org/10.29338/wp2026-19": Response(b"", 302, "https://www.atlantafed.org/landing"),
            "https://www.atlantafed.org/landing": Response(b'<meta property="og:url" content="https://www.atlantafed.org/landing"><a href="/paper.pdf">PDF</a>'),
            "https://fedinprint.org/item/fraser": Response(b'<meta name="citation_pdf_url" content="https://fraser.stlouisfed.org/title/paper">'),
            "https://fraser.stlouisfed.org/title/paper": Response(b'<meta name="citation_pdf_url" content="https://fraser.stlouisfed.org/files/paper.pdf">'),
        }
        class Session:
            def get(inner, url, **kwargs):
                response = pages[url]
                if response.status_code == 302 and kwargs.get("allow_redirects") is not False:
                    raise AssertionError("resolver followed redirect without validation")
                return response
        with patch.object(self.fedinprint, "_get_session", return_value=Session()):
            self.assertEqual(self.fedinprint.resolve_file(ITEM, self.fedinprint.fetch_text), "https://www.atlantafed.org/paper.pdf")
            self.assertEqual(self.fedinprint.resolve_file("https://fedinprint.org/item/fraser", self.fedinprint.fetch_text), "https://fraser.stlouisfed.org/files/paper.pdf")

    def test_resolver_refuses_private_redirect_without_fetching_destination(self):
        seen = []
        class Session:
            def get(inner, url, **kwargs):
                seen.append(url)
                if len(seen) > 1:
                    raise AssertionError("unsafe redirect transport")
                return Response(b"", 302, "https://127.0.0.1/private")
        with patch.object(self.fedinprint, "_get_session", return_value=Session()):
            with self.assertRaises(Exception) as raised:
                self.fedinprint.fetch_text(ITEM)
        self.assertNotIn("unsafe redirect transport", str(raised.exception))
        self.assertEqual(seen, [ITEM])

    def test_download_redirects_share_original_sixty_plus_thirty_second_budget(self):
        elapsed = [0.0]
        calls = []
        def get(url, **kwargs):
            calls.append(kwargs["timeout"])
            elapsed[0] += 61 if len(calls) == 1 else 30
            return Response(b"", 302, PUBLIC)
        with patch("time.monotonic", side_effect=lambda: elapsed[0]), patch("openbb_federal_reserve.utils.curl_session.get_session") as session, patch("openbb_core.provider.utils.helpers.make_request", side_effect=get):
            session.return_value.get.side_effect = get
            with self.assertRaises(TimeoutError):
                self.router._download_pdf(PUBLIC)
        self.assertEqual(calls, [60, 29])

    def test_resolver_403_retry_and_redirects_share_two_attempt_budget(self):
        elapsed = [0.0]
        calls = []
        def get(url, **kwargs):
            calls.append(kwargs["timeout"])
            elapsed[0] += 181
            return Response(b"", 403 if len(calls) == 1 else 302, ITEM)
        with patch("time.monotonic", side_effect=lambda: elapsed[0]), patch.object(self.fedinprint, "_get_session") as session, patch("openbb_federal_reserve.utils.curl_session.reset_session"):
            session.return_value.get.side_effect = get
            with self.assertRaises(TimeoutError):
                self.fedinprint.fetch_text(ITEM)
        self.assertEqual(calls, [180, 179])

    async def test_ffiec_actual_downloader_rejects_http_error_and_keeps_public_pdf(self):
        from openbb_federal_reserve.utils import ffiec
        cases = [
            (self.ffiec.bhcpr_report_download, "https://www.ffiec.gov/npw/StaticData/bhcpRRPT/PeerGroup_1_March2026.pdf"),
            (self.ffiec.financial_report_pdf_download, "https://www.ffiec.gov/npw/FinancialReport/ReturnFinancialReportPDF?rpt=FRY9C&id=123&dt=20260331"),
        ]
        class Session:
            def get(inner, url, **kwargs):
                return response
        for handler, url in cases:
            for status in [403, 200]:
                response = Response(PDF, status)
                with self.subTest(handler=handler.__name__, status=status), patch.object(ffiec, "_get_session", return_value=Session()), patch.object(ffiec, "reset_session"):
                    result = (await handler({"url": [url]}))[0]
                if status == 403:
                    self.assertEqual(result.get("error_type"), "download_error")
                else:
                    self.assertEqual(base64.b64decode(result["content"]), PDF)

    async def test_fomc_rejects_error_html_and_truncated_pdf(self):
        for response in [Response(PDF, 403), Response(b"<html>denied</html>"), Response(b"%PDF-1.4\ntruncated"), Response(PDF, 302, "https://127.0.0.1/private.pdf")]:
            with self.subTest(status=response.status_code, body=response.content), patch("openbb_core.provider.utils.helpers.make_request", return_value=response):
                result = (await self.router.fomc_documents_download({"url": ["https://www.federalreserve.gov/paper.pdf"]}))[0]
                self.assertEqual(result.get("error_type"), "download_error")

    async def test_fomc_refuses_credentials_and_nonstandard_ports_before_transport(self):
        for url in ["https://user:password@www.federalreserve.gov/paper.pdf", "https://www.federalreserve.gov:8443/paper.pdf", "https://www.federalreserve.gov:invalid/paper.pdf"]:
            with self.subTest(url=url), patch("openbb_core.provider.utils.helpers.make_request", side_effect=AssertionError("unsafe FOMC transport")):
                try:
                    result = await self.router.fomc_documents_download({"url": [url]})
                    self.assertNotIn("unsafe FOMC transport", str(result))
                    self.assertEqual(result[0].get("error_type"), "download_error")
                except Exception as exc:
                    self.assertNotIn("unsafe FOMC transport", str(exc))

    async def test_fomc_keeps_pdf_and_html_formats_with_redirects_disabled(self):
        calls = []
        def request(url, **kwargs):
            calls.append(kwargs)
            return Response(PDF if url.endswith(".pdf") else b"<html>Minutes</html>")
        with patch("openbb_core.provider.utils.helpers.make_request", side_effect=request):
            result = await self.router.fomc_documents_download({"url": ["https://www.federalreserve.gov/paper.pdf", "https://www.federalreserve.gov/minutes.htm"]})
        self.assertEqual(base64.b64decode(result[0]["content"]), PDF)
        self.assertEqual(result[1]["data_format"]["data_type"], "markdown")
        self.assertTrue(all(c.get("allow_redirects") is False for c in calls))

    async def test_ffiec_raw_handlers_refuse_non_pdf_bytes(self):
        for name, downloader in [("bhcpr_report_download", "download_bhcpr_pdf"), ("financial_report_pdf_download", "download_financial_report_pdf")]:
            for body in [b"<html>denied</html>", b"%PDF-1.4\ntruncated"]:
                with self.subTest(handler=name, body=body), patch("openbb_federal_reserve.utils.ffiec." + downloader, return_value=body):
                    result = (await getattr(self.ffiec, name)({"url": ["https://www.ffiec.gov/npw/paper.pdf"]}))[0]
                    self.assertEqual(result.get("error_type"), "download_error")

    async def test_blocking_raw_downloads_leave_quick_request_responsive(self):
        def slow(*args, **kwargs):
            time.sleep(.12)
            return PDF
        async def check(handler, target, url, response=False):
            def download(*args, **kwargs):
                body = slow()
                return Response(body) if response else body
            with patch(target, side_effect=download):
                task = asyncio.create_task(handler({"url": [url]}))
                started = time.monotonic()
                await asyncio.sleep(.01)
                elapsed = time.monotonic() - started
                result = await task
            self.assertLess(elapsed, .08)
            self.assertEqual(base64.b64decode(result[0]["content"]), PDF)
        await check(self.router.regional_publications_download, "openbb_federal_reserve.federal_reserve_router._download_pdf", PUBLIC)
        await check(self.router.fomc_documents_download, "openbb_core.provider.utils.helpers.make_request", "https://www.federalreserve.gov/paper.pdf", True)
        for handler, function in [(self.ffiec.bhcpr_report_download, "download_bhcpr_pdf"), (self.ffiec.financial_report_pdf_download, "download_financial_report_pdf")]:
            await check(handler, "openbb_federal_reserve.utils.ffiec." + function, "https://www.ffiec.gov/npw/paper.pdf")

    async def test_blocking_resolver_also_leaves_quick_request_responsive(self):
        def resolve(*args):
            time.sleep(.12)
            return PUBLIC
        with patch.object(self.fedinprint, "resolve_file", side_effect=resolve), patch.object(self.router, "_download_pdf", return_value=PDF):
            task = asyncio.create_task(self.router.regional_publications_download({"url": [ITEM]}))
            started = time.monotonic()
            await asyncio.sleep(.01)
            elapsed = time.monotonic() - started
            result = await task
        self.assertLess(elapsed, .08)
        self.assertEqual(base64.b64decode(result[0]["content"]), PDF)


class FedNicSessionSafety(unittest.TestCase):
    def test_nic_sessions_and_warmup_are_owned_by_calling_thread(self):
        from openbb_federal_reserve.utils import curl_session, ffiec
        sessions = []
        class Session:
            def __init__(self, **kwargs):
                self.owner = threading.get_ident()
                self.calls = []
                sessions.append(self)
            def get(self, url, **kwargs):
                self.assert_owner = threading.get_ident() == self.owner
                self.calls.append(url)
                return Response(PDF)
        barrier = threading.Barrier(2)
        with patch.object(curl_session, "_sessions", {}), patch("curl_cffi.requests.Session", Session):
            ffiec._get_session()  # Prime old global session so a race cannot mask sharing.
            def fetch(_):
                barrier.wait(timeout=2)
                return ffiec._get_session()
            with ThreadPoolExecutor(max_workers=2) as pool:
                one, two = list(pool.map(fetch, [1, 2]))
        self.assertIsNot(one, two)
        self.assertEqual(len(sessions), 3)
        self.assertTrue(all(s.assert_owner for s in sessions))
        self.assertTrue(all(s.calls == ["https://www.ffiec.gov/npw/"] for s in sessions))


    def test_nic_reset_rewarms_only_the_calling_threads_session(self):
        from openbb_federal_reserve.utils import curl_session, ffiec
        class Session:
            def __init__(self, **kwargs):
                self.owner = threading.get_ident()
                self.warmups = []
            def get(self, url, **kwargs):
                self.warmups.append(threading.get_ident())
                return Response()
        barrier = threading.Barrier(2)
        def fetch(reset):
            before = ffiec._get_session()
            barrier.wait(timeout=2)
            if reset:
                ffiec.reset_session()
                ffiec._get_session()
            barrier.wait(timeout=2)
            after = ffiec._get_session()
            return before, after
        with patch.object(curl_session, "_sessions", {}), patch("curl_cffi.requests.Session", Session):
            ffiec._get_session()
            with ThreadPoolExecutor(max_workers=2) as pool:
                reset, unchanged = list(pool.map(fetch, [True, False]))
        self.assertIsNot(reset[0], reset[1])
        self.assertIs(unchanged[0], unchanged[1])
        self.assertEqual(reset[1].warmups, [reset[1].owner])
        self.assertEqual(unchanged[1].warmups, [unchanged[1].owner])


if __name__ == "__main__":
    unittest.main()
