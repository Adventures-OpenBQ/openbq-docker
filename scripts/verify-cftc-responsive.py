#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Fire every CFTC widget at once and require /widgets.json to keep answering meanwhile."""
import argparse
import json
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--max-latency', type=float, default=5.0, help='seconds allowed per /widgets.json poll')
args = parser.parse_args()
base = args.base_url.rstrip('/')


def get(url, timeout):
    started = time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            response.read()
            return response.status, time.monotonic() - started
    except Exception as error:  # an HTTP error status still means the server answered
        return getattr(error, 'code', type(error).__name__), time.monotonic() - started


widgets = json.load(urlopen(base + '/widgets.json', timeout=60))
urls = {}
for wid, widget in widgets.items():
    if wid.startswith('cftc_'):
        params = {p['paramName']: p['value'] for p in widget.get('params', []) if p.get('value') not in (None, '')}
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        urls[wid] = base + widget['endpoint'] + '?' + urllib.parse.urlencode(params)
assert urls, 'No CFTC widgets in widgets.json'

done, polls = threading.Event(), []


def poll():
    while not done.is_set():
        polls.append(get(base + '/widgets.json', args.max_latency))
        time.sleep(1)


poller = threading.Thread(target=poll)
poller.start()
with ThreadPoolExecutor(len(urls)) as pool:
    results = dict(zip(urls, pool.map(lambda url: get(url, 900), urls.values())))
done.set()
poller.join()

slow = [(status, round(seconds, 2)) for status, seconds in polls if status != 200 or seconds > args.max_latency]
print(json.dumps({'cftc_widgets': {wid: status for wid, (status, _) in results.items()},
                  'widgets_json_polls': len(polls),
                  'widgets_json_max_seconds': round(max(s for _, s in polls), 2),
                  'slow_or_failed_polls': slow}))
assert not slow, 'widgets.json stalled while CFTC widgets ran'
print(json.dumps({'status': 'passed'}))
