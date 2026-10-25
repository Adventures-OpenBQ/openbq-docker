#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Verify the BLS and Federal Reserve empty file selections and app references over HTTPS."""
import argparse
import json
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
args = parser.parse_args()
base = args.base_url.rstrip('/')


def fetch(path, body=None):
    request = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                      headers={} if body is None else {'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        assert response.status == 200
        return json.load(response)


widgets = fetch('/widgets.json')
endpoints = {w['endpoint'] for wid, w in widgets.items()
             if wid.startswith('bls_') and w.get('endpoint', '').endswith('/document_download')}
assert len(endpoints) == 7, 'Expected seven BLS document handlers'
for endpoint in sorted(endpoints):
    assert fetch(endpoint, {'url': None}) == [], 'Null selection must return an empty result'
    assert fetch(endpoint, {'url': []}) == [], 'Empty selection must return an empty result'

fed = {wid: w['endpoint'] for wid, w in widgets.items()
       if w.get('endpoint', '').startswith('/api/v1/federal_reserve/') and w['endpoint'].endswith('_download')}
assert len(fed) == 17, 'Expected seventeen Federal Reserve file viewers'
for endpoint in sorted(set(fed.values())):
    assert fetch(endpoint, {'url': None}) == [], 'Null selection must return an empty result'
    assert fetch(endpoint, {'url': []}) == [], 'Empty selection must return an empty result'

apps = fetch('/apps.json')
missing = set()
for app in apps:
    for tab in app.get('tabs', {}).values():
        for widget in tab.get('layout', []):
            wid = widget['i']
            if wid not in widgets:
                missing.add(wid)
assert 'economy_calendar_bls_obb' not in missing, 'Unresolved BLS calendar reference'
assert not any(wid.startswith('tmx_derivatives_options_') for wid in missing), 'Unresolved TMX options reference'
assert 'bls_calendar_bls_obb' in widgets or 'economy_calendar_bls_obb' in widgets
print(json.dumps({'bls_document_checks': 14, 'federal_reserve_viewer_checks': 2 * len(set(fed.values())), 'app_layout_missing_references': len(missing), 'status': 'passed'}))
