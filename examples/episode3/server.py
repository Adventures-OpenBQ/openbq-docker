# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Local, keyless Episode 3 fixture backend. Fictional data only."""
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'data.json').read_text())
APPS = json.loads((ROOT / 'apps.json').read_text())
WIDGETS = {
    'openbq_demo_' + sample: {
        'name': 'Fictional ' + sample.title(),
        'description': 'Deterministic fictional data for Episode 3 pivot arithmetic; not market data.',
        'type': 'table', 'category': 'Episode 3', 'endpoint': 'data/' + sample,
        'gridData': {'w': 40, 'h': 20}, 'params': []
    } for sample in DATA
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def respond(self, status, payload=None, content_type='application/json'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else b''
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.end_headers()
        self.wfile.write(body)
    def do_OPTIONS(self):
        self.respond(204)
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/assets/bdobb-logo.svg':
            self.respond(200, (ROOT / 'assets/bdobb-logo.svg').read_bytes(), 'image/svg+xml')
            return
        routes = {'/widgets.json': WIDGETS, '/apps.json': APPS,
                  '/agents.json': {}, '/health': {'status': 'ok'},
                  **{'/data/' + name: rows for name, rows in DATA.items()}}
        if path not in routes:
            self.respond(404, {'error': 'Not found'})
        else:
            self.respond(200, routes[path])

if __name__ == '__main__':
    ThreadingHTTPServer((os.environ.get('DEMO_HOST', '127.0.0.1'),
                         int(os.environ.get('DEMO_PORT', '17783'))), Handler).serve_forever()
