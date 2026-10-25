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

    def test_every_api_image_builds_installs_and_gates_openbq_eodhd(self):
        # v9: the api stage installs openbq-eodhd from v9/eodhd/source; the v3 stage builds FROM api.
        for name in API_DOCKERFILES:
            text = dockerfile(name)
            with self.subTest(name):
                self.assertIn("COPY v9/eodhd/source /eodhd", text)
                self.assertIn("--wheel-dir /wheels /eodhd", text)
                self.assertIn("python -m pip install --no-deps /tmp/ext/*.whl", text)
                # The SDK is vendored in openbq-eodhd 9.0.1; nothing fetches or pins it separately.
                self.assertNotIn("EODHD-APIs-Python-Financial-Library", text)
                self.assertNotIn("/tmp/eodhd/extra.lock", text)
                self.assertIn("/wheels/openbq_eodhd-9.0.1-py3-none-any.whl /tmp/ext/", text)
                self.assertIn("python /tmp/ext-verify/eodhd/verify.py", text)

    def test_the_api_service_gets_eodhd_api_key_from_the_credentials_files(self):
        import yaml

        api = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["openbq-api"]
        paths = [f["path"] for f in api["env_file"]]
        self.assertEqual(paths, ["./credentials.demo.env", "./credentials.env"])
        self.assertIn("EODHD_API_KEY", (ROOT / "credentials.env.example").read_text())
        self.assertIn("EODHD_API_KEY=demo", (ROOT / "credentials.demo.env").read_text().splitlines())

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

    def test_the_v6_overlay_builds_rita_and_mcp_locally(self):
        # The GHCR images are private: Rita comes from agent-rita-bdobb's build.sh and MCP
        # builds from ./mcp on this release's API image. Compose must never pull either.
        release = re.search(r"image: openbq-key-maint:(\S+)",
                            dockerfile("docker-compose.v3.yml")).group(1)
        overlay = dockerfile("docker-compose.v6.yml")
        self.assertNotIn("ghcr.io", overlay)
        self.assertIn("image: openbq-rita:6.0.0\n    pull_policy: never\n", overlay)
        self.assertIn(f"image: openbq-mcp:{release}\n    pull_policy: never\n", overlay)
        self.assertIn("context: ./mcp", overlay)
        self.assertIn("base: service:openbq-api", overlay)
        self.assertIn(f"ARG BASE=openbq-local:{release}\n", dockerfile("mcp/Dockerfile"))

    def test_the_doors_rita_holds_no_paid_provider_key(self):
        # openbq-rita-door is the second layer behind the gateway's forced model: every provider
        # key agent-rita reads, other than the Spark's OpenAI-compatible endpoint, is blanked.
        overlay = dockerfile("docker-compose.v6.yml")
        door = overlay.split("  openbq-rita-door:\n", 1)[1].split("\n  openbq-mcp:", 1)[0]
        self.assertIn("path: ./rita-door.env", door)
        self.assertIn('PORT: "7778"', door)
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENROUTER_API_KEY", "GROQ_API_KEY", "OLLAMA_BASE_URL"):
            self.assertIn(f'{key}: ""', door, key)
        self.assertIn("aliases: [openbq-rita-door]", overlay)
        # It refuses to start without the Spark's endpoint: unset, "openai:" is OpenAI itself.
        self.assertIn('"" | *api.openai.com*) echo', door)
        self.assertIn("exec bun src/server.ts", door)
        example = dockerfile("rita-door.env.example")
        self.assertNotIn("ANTHROPIC", example.replace("# ", ""))


if __name__ == "__main__":
    unittest.main()
