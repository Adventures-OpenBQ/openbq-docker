# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
import json
import threading
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError
from server import Handler, ThreadingHTTPServer

class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
    def get(self, path):
        with urlopen(self.base + path) as r:
            return json.load(r), r.headers
    def test_bdobb_branding(self):
        apps, _ = self.get('/apps.json')
        for app in apps:
            if app['name'].startswith('Episode 3'):
                for field in ('img', 'img_dark', 'img_light'):
                    self.assertTrue(app[field].startswith('data:image/svg+xml;base64,'))
        with urlopen(self.base + '/assets/bdobb-logo.svg') as response:
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
            self.assertIn(b'<svg', response.read())

    def test_bdobb_logo_does_not_open_arbitrary_files(self):
        with self.assertRaises(HTTPError) as e:
            urlopen(self.base + '/assets/../server.py')
        self.assertEqual(e.exception.code, 404)

    def test_catalog_and_data(self):
        apps, _ = self.get('/apps.json')
        widgets, headers = self.get('/widgets.json')
        self.assertEqual(len(apps), 3)
        self.assertEqual(set(widgets), {'openbq_demo_prices', 'openbq_demo_nulls'})
        self.assertEqual(headers['Access-Control-Allow-Origin'], '*')
        for w in widgets.values():
            data, _ = self.get('/' + w['endpoint'])
            self.assertEqual(len(data), 5)
        with self.assertRaises(HTTPError) as e:
            urlopen(self.base + '/unknown')
        self.assertEqual(e.exception.code, 404)
