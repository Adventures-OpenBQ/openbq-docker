# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The TMX screener builder needs pywry, which the image does not install; it is not offered."""
import asyncio
import json
import unittest

BUILDER = "tmx_equity_screener_builder_obb"


class TmxScreenerBuilderExcludedTest(unittest.TestCase):
    def test_widget_absent_from_widgets_json(self):
        from openbb_core.api.rest_api import app
        from openbb_platform_api.utils.widgets import build_json

        openapi = app.openapi()
        widgets = build_json(openapi, [])
        self.assertIn("/api/v1/tmx/equity/screener_builder/view", openapi["paths"])
        self.assertIn("tmx_equity_screener_tmx_obb", widgets)
        self.assertFalse(BUILDER in widgets)

    def test_apps_json_does_not_reference_it(self):
        from openbb_tmx.tmx_router import tmx_apps

        apps = asyncio.run(tmx_apps())
        self.assertNotIn(BUILDER, json.dumps(apps))
        self.assertTrue(all(t["layout"] for a in apps for t in a["tabs"].values()))


if __name__ == "__main__":
    unittest.main()
