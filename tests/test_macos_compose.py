# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Docker Desktop must keep the privileged Unix socket on a Linux volume."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacOSComposeTests(unittest.TestCase):
    def test_admin_socket_uses_named_volume_without_new_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("docker-compose.yml", "docker-compose.v3.yml", "docker-compose.macos.yml"):
                shutil.copyfile(ROOT / name, root / name)
            for name in ("ts.env", "credentials.env", "credentials.demo.env", "workspace/runtime.env", "workspace/ts.env", "gateway.env"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            def config(extra):
                command = ["docker", "compose", "-p", "openbq-macos-contract", "-f", "docker-compose.yml", "-f", "docker-compose.v3.yml"]
                for name in extra:
                    command += ["-f", name]
                return json.loads(subprocess.check_output(command + ["config", "--format", "json"], cwd=root))

            baseline = config([])
            actual = config(["docker-compose.macos.yml"])
            service = actual["services"]["key-maint"]
            mount = next(v for v in service["volumes"] if v["target"] == "/config/admin")
            self.assertEqual(mount["type"], "volume")
            self.assertEqual(mount["source"], "key-maint-admin")
            self.assertIn("key-maint-admin", actual["volumes"])
            self.assertEqual(service["ports"], baseline["services"]["key-maint"]["ports"])
            self.assertEqual(service["networks"], baseline["services"]["key-maint"]["networks"])
            original = next(v for v in baseline["services"]["key-maint"]["volumes"] if v["target"] == "/config/admin")
            self.assertEqual(original["type"], "bind")
