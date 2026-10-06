"""Integration checks against the assembled, pinned OpenBQ app (no fake registry)."""
import base64
import json
import unittest
from fastapi.testclient import TestClient
from reference_app import app

class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
    def test_catalog_resolution(self):
        widgets = self.client.get('/widgets.json').json()
        apps = self.client.get('/apps.json').json()
        self.assertEqual(len(apps), 2)
        self.assertEqual(sum(len(t['layout']) for a in apps for t in a['tabs'].values()), 73)
        self.assertNotIn('omni-python-widget', widgets)
        for a in apps:
            for tab in a['tabs'].values():
                for card in tab['layout']:
                    self.assertIn(card['i'], widgets)
        bundle = self.client.get('/bundle.apps.json').json()
        self.assertEqual(len(bundle), 3)
        self.assertEqual(sum(len(t['layout']) for a in bundle for t in a['tabs'].values()), 79)
        optional = self.client.get('/market-examples.apps.json').json()
        self.assertEqual(len(optional), 1)
        market = {card['i'] for a in optional for t in a['tabs'].values() for card in t['layout']}
        missing = market - widgets.keys() - {'note'}
        self.assertEqual(len(missing), 5)  # SEC + four yfinance routes.
    def test_reference_routes_and_pdf(self):
        self.assertEqual(self.client.get('/metric_widget').json()[0]['value'], '1,234,567')
        self.assertEqual(len(self.client.get('/table_widget').json()), 3)
        pdf = self.client.get('/pdf_widget_base64').json()
        self.assertTrue(base64.b64decode(pdf['content']).startswith(b'%PDF'))
        self.assertEqual(self.client.post('/form_submit', json={}).status_code, 400)
        self.assertIn(self.client.post('/omni-python-widget', json={}).status_code, (404, 405))
    def test_pivot_and_logo(self):
        self.assertEqual(len(self.client.get('/data/prices').json()), 5)
        self.assertEqual(len(self.client.get('/data/nulls').json()), 5)
        r = self.client.get('/assets/bdobb-logo.svg')
        self.assertEqual(r.status_code, 200)
        self.assertIn('image/svg+xml', r.headers['content-type'])
        self.assertEqual(self.client.get('/assets/../core.py').status_code, 404)
        self.assertEqual(self.client.get('/health').json()['status'], 'ok')
    def test_duplicate_demo_registration_refuses_without_mutation(self):
        from reference_app import install_demo
        from core import WIDGETS
        before = dict(WIDGETS)
        with self.assertRaisesRegex(ValueError, 'collide'):
            install_demo(app, WIDGETS)
        self.assertEqual(WIDGETS, before)

    def test_cors(self):
        r = self.client.options('/widgets.json', headers={'Origin':'https://demo.example.org','Access-Control-Request-Method':'GET'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['access-control-allow-origin'], 'https://demo.example.org')
    def test_live_grid_websocket(self):
        with self.client.websocket_connect('/live_grid_ws') as ws:
            ws.send_json({'params': {'symbol': 'AAPL'}})
            message = ws.receive_json()
            self.assertTrue(message)
