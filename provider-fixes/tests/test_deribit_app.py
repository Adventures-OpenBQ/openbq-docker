# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The overlaid Deribit app: its image URL has a single slash after the host (stdlib only)."""
import json
import unittest
from pathlib import Path

APPS = Path(__file__).resolve().parents[1] / "openbb_deribit" / "assets" / "apps.json"


class DeribitApp(unittest.TestCase):
    def test_image_urls_have_no_doubled_slash(self):
        apps = json.loads(APPS.read_text())
        apps = apps if isinstance(apps, list) else [apps]
        images = [app[key] for app in apps for key in ("img", "img_dark", "img_light") if app.get(key)]
        self.assertIn("https://www.deribit.com/share-image.png", images)
        for url in images:
            self.assertNotIn("//", url.split("://", 1)[-1], url)


if __name__ == "__main__":
    unittest.main()
