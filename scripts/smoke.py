#!/usr/bin/env python3
"""Verify a running Episode 1 API; failures exit nonzero. No credentials logged."""
import argparse
import json
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--data-path', default='/api/v1/cboe/equity/quote?symbol=AAPL&provider=cboe')
args = parser.parse_args()
base = args.base_url.rstrip('/')

def fetch(path):
    with urlopen(base + path, timeout=90) as response:
        assert response.status == 200, f'{path}: HTTP {response.status}'
        return json.load(response)

widgets = fetch('/widgets.json')
assert isinstance(widgets, dict) and widgets, 'Empty or invalid widget catalogue'
schema = fetch('/openapi.json')
assert schema.get('openapi') and schema.get('paths'), 'Invalid OpenAPI schema'
assert '/api/v1/cboe/equity/quote' in schema['paths'], 'Expected V5 CBOE route missing'
fetch('/apps.json')
fetch('/agents.json')
result = fetch(args.data_path)
rows = result.get('results')
assert rows and isinstance(rows, (list, dict)), 'Data request returned no results'
print(json.dumps({'widgets': len(widgets), 'routes': len(schema['paths']),
                  'data_path': args.data_path, 'data_rows': len(rows), 'status': 'passed'}, indent=2))
