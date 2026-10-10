#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Compare every lane-routed widget's default between a D8 API and one with OPENBQ_ISOLATE empty.

Status, content type and body must match; only the per-call OBBject fields
(id, extra.metadata.duration and .timestamp) may differ.
"""
import argparse
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('lane_url')
parser.add_argument('in_process_url')
parser.add_argument('--prefixes', default='/api/v1/cftc/,/api/v1/finra/fixedincome/bonds')
args = parser.parse_args()
prefixes = tuple(args.prefixes.split(','))


def get(url):
    try:
        with urlopen(url, timeout=900) as response:
            return response.status, response.headers.get('content-type'), response.read()
    except Exception as error:
        return getattr(error, 'code', type(error).__name__), None, getattr(error, 'read', lambda: b'')()


def normal(body):
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, dict):
        data.pop('id', None)
        for key in ('duration', 'timestamp'):
            ((data.get('extra') or {}).get('metadata') or {}).pop(key, None)
    return data


widgets = json.load(urlopen(args.lane_url.rstrip('/') + '/widgets.json', timeout=60))
paths = {}
for wid, widget in widgets.items():
    endpoint = widget.get('endpoint', '')
    if endpoint.startswith(prefixes) and not endpoint.endswith('_choices'):
        params = {p['paramName']: p['value'] for p in widget.get('params', []) if p.get('value') not in (None, '')}
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        paths[wid] = endpoint + '?' + urllib.parse.urlencode(params)
assert paths, 'No lane-routed widgets'

mismatched, results = [], {}
for wid, path in sorted(paths.items()):
    with ThreadPoolExecutor(2) as pool:  # both at once, so live data has no time to move
        lane, local = pool.map(get, (args.lane_url.rstrip('/') + path, args.in_process_url.rstrip('/') + path))
    same = lane[:2] == local[:2] and normal(lane[2]) == normal(local[2])
    results[wid] = lane[0]
    if not same:
        mismatched.append({'widget': wid, 'lane': lane[:2], 'in_process': local[:2]})
print(json.dumps({'widgets': results, 'mismatched': mismatched}))
assert not mismatched, 'lane responses differ from in-process responses'
print(json.dumps({'status': 'passed', 'compared': len(paths)}))
