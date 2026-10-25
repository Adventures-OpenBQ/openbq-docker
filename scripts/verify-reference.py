#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Verify the self-contained reference catalog against its actual HTTP registry."""
import json
import sys
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip('/')
def fetch(path):
    with urlopen(base + path, timeout=20) as r:
        return json.load(r)

widgets = fetch('/widgets.json')
apps = fetch('/apps.json')
ids = [c['i'] for a in apps for t in a['tabs'].values() for c in t['layout']]
missing = sorted(set(ids) - widgets.keys())
assert len(apps) == 1 and len(ids) == 70, 'Unexpected self-contained app catalog'
assert len(widgets) == 72, 'Unexpected widget registry'
assert not missing, 'App layout references absent widgets'
assert 'omni-python-widget' in widgets, 'Python Omni widget must be served (gated by OPENBQ_OMNI_EXEC_ALLOWED)'
assert len(fetch('/data/prices')) == 5 and len(fetch('/data/nulls')) == 5
assert len(fetch('/table_widget')) == 3
assert fetch('/metric_widget')[0]['value'] == '1,234,567'
assert fetch('/health')['status'] == 'ok'
bundle = fetch('/bundle.apps.json')
assert len(bundle) == 2
assert not [c for a in bundle for t in a['tabs'].values() for c in t['layout'] if 'extensions' in c], 'BDOBB v3 refuses layout extensions'
assert len(fetch('/market-examples.apps.json')) == 1
for app in bundle:
    if app['name'].startswith('Episode 3'):
        assert all(app[k].startswith('data:image/svg+xml;base64,') for k in ('img', 'img_dark', 'img_light'))
with urlopen(base + '/assets/bdobb-logo.svg', timeout=20) as r:
    assert r.headers['Content-Type'].startswith('image/svg+xml') and b'<svg' in r.read()
print(json.dumps({'status':'passed','widgets':len(widgets),'apps':len(apps),'cards':len(ids),'missing_references':len(missing)}))
