# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Exercise the Docker health command against a real HTTP server, with and without auth."""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
USER = 'health-test'
PASSWORD = 'test: password & punctuation'


@contextmanager
def endpoint(require_auth):
    expected = 'Basic ' + base64.b64encode(f'{USER}:{PASSWORD}'.encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if not require_auth or self.headers.get('Authorization') == expected else 401)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/widgets.json'
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def probe(url, enabled, password=PASSWORD):
    text = (ROOT / 'Dockerfile').read_text()
    command = re.search(r'^HEALTHCHECK .+ CMD (.+)$', text, re.M).group(1)
    command = command.replace('http://127.0.0.1:6900/widgets.json', url)
    if command.startswith('['):
        command = json.loads(command)
        command[0] = sys.executable
        command = [str(ROOT / 'scripts/healthcheck.py') if part == '/usr/local/bin/openbq-healthcheck.py' else part for part in command]
    else:
        command = ['sh', '-c', command]
    env = dict(os.environ, OPENBB_API_AUTH='true' if enabled else '', OPENBB_API_USERNAME=USER, OPENBB_API_PASSWORD=password)
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)


class HealthcheckTests(unittest.TestCase):
    def test_open_api_is_healthy(self):
        with endpoint(False) as url:
            self.assertEqual(probe(url, False).returncode, 0)

    def test_authenticated_api_is_healthy(self):
        with endpoint(True) as url:
            result = probe(url, True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(PASSWORD, result.stdout + result.stderr)

    def test_wrong_credential_remains_unhealthy(self):
        with endpoint(True) as url:
            result = probe(url, True, password='incorrect-test-password')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('incorrect-test-password', result.stdout + result.stderr)
