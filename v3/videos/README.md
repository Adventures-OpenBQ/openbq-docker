<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Video Library extension (openbb-videos)

`source/` is `openbb-videos` 3.0.1, vendored from bdobb-dev/openbb-docker (branch
`claude/video-library`, commit `13816e1`, after v8.0.3; `source.json`). There is no PyPI release. It is
an OpenBB router extension serving `GET /api/v1/videos/video`, whose widget is
**`videos_video_custom_obb`** ("Video Library", type `youtube`, no key). The body is the bare
YouTube watch URL as `text/plain`, not an OBBject, because that is what BDOBB's YouTube card reads;
`video_name` picks one of two sample videos (default "OpenBB Workspace Demo"), and an unknown name
answers an empty body.

The two sample videos, the widget definition and its parameter are adapted from OpenBB's reference
backend (`backends-for-openbb`, `getting-started/reference-backend/widgets_youtube.py`, MIT License,
Copyright (c) 2024 OpenBB); the MIT notice is reproduced in `source/openbb_videos/router.py`. The rest
is Apache-2.0. The only local change is the build backend (hatchling, as the image's pinned wheel
builder, instead of setuptools).

`Dockerfile` builds the wheel in a pinned builder stage and install it with
`--no-deps` (its only dependency, openbb-core, is in `requirements.lock`, which is unchanged); `verify.py`
is the build gate. `source/tests` run against an installed openbb-core 2.0.1 (5 tests).
