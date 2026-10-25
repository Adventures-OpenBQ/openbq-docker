# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Build gate: the Video Library route and widget through the real ODP app."""
import importlib.metadata as metadata

from fastapi.testclient import TestClient
from openbb_core.api.rest_api import app
from openbb_platform_api.utils.widgets import build_json

assert metadata.version('openbb-videos') == '3.0.1'
client = TestClient(app)
r = client.get('/api/v1/videos/video', params={'video_name': 'OpenBB Workspace Demo'})
assert r.status_code == 200 and r.headers['content-type'].startswith('text/plain'), r.text
assert r.text == 'https://www.youtube.com/watch?v=uYyhswnZkSw', r.text
widget = build_json(app.openapi(), [])['videos_video_custom_obb']
assert widget['type'] == 'youtube' and widget['name'] == 'Video Library', widget
print('PASS: openbb-videos 3.0.1, videos_video_custom_obb (youtube) answers a bare watch URL')
