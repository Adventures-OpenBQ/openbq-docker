# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Static checks of the API images (stdlib unittest; run: python3 -m unittest discover tests).

Images are built on the Mac; these pin what every API Dockerfile must install and copy.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DOCKERFILES = ["Dockerfile"]  # openbq-api: target v3 (docker-compose.yml), the full API image


def dockerfile(name):
    return (ROOT / name).read_text()


class ApiImages(unittest.TestCase):
    def test_every_api_dockerfile_is_listed(self):
        found = sorted(p.name for p in ROOT.glob("Dockerfile*") if "openbq_lanes.py" in p.read_text())
        self.assertEqual(found, sorted(API_DOCKERFILES))

    def test_videos_and_econdb_are_built_from_the_vendored_sources_and_gated(self):
        for name in API_DOCKERFILES:
            text = dockerfile(name)
            with self.subTest(name):
                self.assertIn("COPY v3/videos/source /videos", text)
                self.assertIn("COPY v3/econdb/source /econdb", text)
                self.assertIn("--wheel-dir /wheels /videos /econdb", text)
                self.assertRegex(text, r"/wheels/openbb_videos-3\.0\.1-py3-none-any\.whl "
                                       r"/wheels/openbb_econdb-1\.0\.0\+openbq\.1-py3-none-any\.whl /tmp/ext/")
                self.assertIn("python -m pip install --no-deps /tmp/ext/*.whl && python -m pip check && openbb-build", text)
                self.assertIn("python /tmp/ext-verify/videos.py && python /tmp/ext-verify/econdb/verify.py", text)

    def test_wheel_names_match_the_vendored_versions(self):
        videos = (ROOT / "v3/videos/source/pyproject.toml").read_text()
        econdb = (ROOT / "v3/econdb/source/pyproject.toml").read_text()
        self.assertRegex(videos, r'(?m)^name = "openbb-videos"\nversion = "3\.0\.1"$')
        self.assertRegex(econdb, r'(?m)^name = "openbb-econdb"\nversion = "1\.0\.0\+openbq\.1"$')

    def test_the_lock_is_unchanged_by_the_vendored_extensions(self):
        lock = (ROOT / "requirements.lock").read_text()
        for name in ("openbb-videos", "openbb-econdb", "nest-asyncio", "nest_asyncio"):
            self.assertNotIn(name, lock.lower())
        for dependency in ("openbb-core==2.0.1", "aiohttp-client-cache==", "aiosqlite=="):
            self.assertIn(dependency, lock)

    def test_examples_and_logo_are_copied_into_every_api_image(self):
        for name in API_DOCKERFILES:
            text = dockerfile(name)
            with self.subTest(name):
                self.assertIn("COPY examples/bdobb/apps.json /workspace/bdobb_apps.json", text)
                self.assertIn("COPY examples/episode3/assets/bdobb-logo.svg /workspace/bdobb-logo.svg", text)
                self.assertTrue(re.search(r"(?m)^WORKDIR /workspace$", text))

    def test_fixture_widgets_are_copied_into_every_api_image(self):
        for name in API_DOCKERFILES:
            with self.subTest(name):
                self.assertIn("COPY v5/fixtures /workspace/openbq-fixtures", dockerfile(name))

    def test_the_base_compose_builds_the_full_api_image_under_the_release_version(self):
        # docker-compose.yml alone must build the stage that installs yfinance and the v4 routes,
        # and a local build must not overwrite an earlier release's images. The gateway keeps the
        # version it was brought down at (4.0.0 for v4-v7), so the release is the overlay's
        # key-maint tag.
        base = dockerfile("docker-compose.yml")
        overlay = dockerfile("docker-compose.v3.yml")
        release = re.search(r"image: openbq-key-maint:(\S+)", overlay).group(1)
        self.assertIn("build: {context: ., target: v3}\n", base)
        self.assertIn(f"image: openbq-local:{release}\n", base)
        stage = dockerfile("Dockerfile").split("FROM api AS v3\n", 1)[1]
        self.assertIn("openbq_yfinance-3.0.0-py3-none-any.whl", stage)
        self.assertIn("openbq_routes-4.0.0-py3-none-any.whl", stage)
        self.assertNotRegex(overlay, r"(?m)^  openbq-api:")  # no second, divergent API build
        self.assertIn(f"image: openbq-episode3-demo:{release}\n", overlay)


if __name__ == "__main__":
    unittest.main()
