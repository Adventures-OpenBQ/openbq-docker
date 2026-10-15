# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
#
# Portions adapted from OpenBB's reference backend, backends-for-openbb,
# getting-started/reference-backend/widgets_youtube.py
# (https://github.com/OpenBB-finance/backends-for-openbb): the two sample
# videos, the "Video Library" widget and its parameter, and the endpoint's
# plain-text answer. Those portions remain under the licence below.
#
# MIT License
#
# Copyright (c) 2024 OpenBB
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""OpenBB Platform router: /api/v1/videos/video, the Video Library widget.

A plain-text command, not an OBBject one: the body is the bare YouTube watch
URL, which is what bdobb's YouTube card reads. An OBBject would wrap it in
`results`. The command is annotated `-> str` (a class that is not an OBBject,
so openbb_core's Router.command leaves it alone and the API wrapper passes the
value through) and answers as text/plain through `response_class`. The options
are a static list in widget_config rather than the reference's options
endpoint: two fixed videos need no second route."""

# No `from __future__ import annotations` here. Router.command decides between
# an OBBject command and a plain one with isclass() on the return annotation,
# and a string annotation is not a class.
from fastapi.responses import PlainTextResponse
from openbb_core.app.router import Router

router = Router(prefix="", description="Video Library: YouTube videos for the YouTube card.")

SAMPLE_VIDEOS = {
    "OpenBB Workspace Demo": "https://www.youtube.com/watch?v=uYyhswnZkSw",
    "Open Data Platform Demo": "https://www.youtube.com/watch?v=MSlhOFxEdxg",
}
DEFAULT_VIDEO = "OpenBB Workspace Demo"


@router.command(
    methods=["GET"],
    response_class=PlainTextResponse,
    widget_config={
        "name": "Video Library",
        "category": "Videos",
        "description": "View YouTube videos",
        "type": "youtube",
        "gridData": {"w": 20, "h": 12},
        "params": [
            {
                "paramName": "video_name",
                "description": "Video to display",
                "label": "Video",
                "type": "text",
                "value": DEFAULT_VIDEO,
                "options": [{"label": name, "value": name} for name in SAMPLE_VIDEOS],
            }
        ],
    },
)
async def video(video_name: str = DEFAULT_VIDEO) -> str:
    """The watch URL of one sample video; an empty body for an unknown name."""
    return SAMPLE_VIDEOS.get(video_name, "")
