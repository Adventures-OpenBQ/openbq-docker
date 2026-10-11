#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Fail when two cards on one app tab overlap (Workspace then pushes cards down on first display).

Takes an API base URL (reads /apps.json) or a path to an apps.json file.
"""
import json
import sys
from urllib.request import urlopen

source = sys.argv[1]
if source.startswith('http'):
    apps = json.load(urlopen(source.rstrip('/') + '/apps.json', timeout=60))
else:
    apps = json.load(open(source))
apps = apps if isinstance(apps, list) else [apps]

overlaps = []
for app in apps:
    for tab_id, tab in (app.get('tabs') or {}).items():
        cards = tab.get('layout') or []
        for n, a in enumerate(cards):
            for b in cards[n + 1:]:
                if (a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w']
                        and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']):
                    overlaps.append(f"{app.get('name')} / {tab_id}: {a['i']} overlaps {b['i']}")
print(json.dumps({'apps': len(apps), 'overlaps': overlaps}, indent=1))
assert not overlaps, 'overlapping cards'
print(json.dumps({'status': 'passed'}))
