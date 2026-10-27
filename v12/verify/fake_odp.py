# v12/verify/fake_odp.py
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""A fake ODP for verify-charts.sh: a bar for every weekday (prices a function of the date),
on the yfinance and EODHD history routes. The calendar route 404s (arts-charts treats it as
an outage). No upstream, no key."""
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if not url.path.endswith('/historical'):
            self.send_response(404); self.end_headers(); return
        q = parse_qs(url.query)
        day, last, rows = date.fromisoformat(q['start_date'][0]), date.fromisoformat(q['end_date'][0]), []
        while day <= last:
            if day.weekday() < 5:
                o = day.toordinal() % 97 + 100.0
                rows.append({'date': day.isoformat(), 'open': o, 'high': o + 2, 'low': o - 2,
                             'close': o + 1, 'adjusted_close': o + 1, 'volume': 1000.0 + day.day})
            day += timedelta(days=1)
        body = json.dumps({'results': rows}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('0.0.0.0', 6900), Handler).serve_forever()
