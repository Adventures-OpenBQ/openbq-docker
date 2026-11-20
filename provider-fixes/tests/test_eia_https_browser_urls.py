# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Nested EIA resources must follow the browser origin through HTTPS proxies."""
import json
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from openbb_us_eia import browsers, rss

class BrowserUrls(unittest.IsolatedAsyncioTestCase):
    async def payload(self, info):
        response = await browsers.render_browser('electricity', 'dark', False, info)
        return json.loads(re.search(r'<script id="browser-data" type="application/json">(.*?)</script>', response.body.decode(), re.S).group(1))

    async def test_request_path_keeps_browser_resources_on_external_https_origin(self):
        payload = await self.payload({'url': 'http://internal:6900/nested/api/v1/eia/electricity_browser', 'path': '/nested/api/v1/eia/electricity_browser'})
        self.assertEqual(payload['endpoint'], '/nested/api/v1/eia/electricity_browser')
        self.assertEqual(payload['proxy'], '/nested/api/v1/eia/eia_proxy')
        for name in ['src', 'home']:
            self.assertTrue(payload[name].startswith('/nested/api/v1/eia/eia_proxy/'))
            self.assertNotIn('http://internal', payload[name])

    async def test_absolute_url_only_info_still_yields_origin_relative_browser_resources(self):
        payload = await self.payload({'url': 'https://public.example/api/v1/eia/electricity_browser'})
        self.assertEqual(payload['endpoint'], '/api/v1/eia/electricity_browser')
        self.assertEqual(payload['proxy'], '/api/v1/eia/eia_proxy')

    async def test_direct_sdk_fallback_without_request_is_preserved(self):
        with patch.dict('os.environ', {'OPENBB_API_HOST': '127.0.0.1', 'OPENBB_API_PORT': '6900'}):
            payload = await self.payload(None)
        self.assertEqual(payload['endpoint'], 'http://127.0.0.1:6900/api/v1/eia/electricity_browser')

    async def test_international_uses_current_official_csv_data_portal(self):
        response = await browsers.render_browser('international', 'dark', False, {'path': '/api/v1/eia/international_browser'})
        payload = json.loads(re.search(r'<script id="browser-data" type="application/json">(.*?)</script>', response.body.decode(), re.S).group(1))
        self.assertEqual(payload['path'], 'international/data/')
        self.assertIn('/eia_proxy/international/data/', payload['home'])

    async def test_home_navigation_does_not_leave_a_blank_frame_waiting_for_paint(self):
        response = await browsers.render_browser('electricity', 'dark', False, {'path': '/api/v1/eia/electricity_browser'})
        home = response.body.decode().split('function goHome() {', 1)[1].split('window.__eiaGoHome', 1)[0]
        self.assertIn('frame.src = DATA.home;', home)
        self.assertNotIn('requestAnimationFrame(', home)
        self.assertNotIn('about:blank', home)

    async def test_rss_endpoint_and_article_proxy_are_origin_relative(self):
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        info = {'url': 'http://internal:6900/prefix/api/v1/eia/rss_feed', 'path': '/prefix/api/v1/eia/rss_feed'}
        with patch('openbb_core.provider.utils.helpers.get_async_requests_session', AsyncMock(return_value=session)), patch('openbb_us_eia.utils.rss.fetch_feed', AsyncMock(return_value={})), patch.object(rss, 'build_feed', return_value={}) as build, patch.object(rss, 'render_rss_html', return_value='<p>feed</p>') as render:
            await rss.rss_feed(info=info)
        self.assertEqual(build.call_args.args[3], '/prefix/api/v1/eia/eia_proxy')
        self.assertEqual(render.call_args.args[0]['endpoint'], '/prefix/api/v1/eia/rss_feed')

if __name__ == '__main__':
    unittest.main()
