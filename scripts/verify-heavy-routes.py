#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Run the heavy routes together and require /widgets.json and /apps.json to keep answering (D8).

CFTC forex swap_trades and FINRA MBS go to the worker lane; OECD dataflows and
TMX covered calls stay in process. Passes when every probe answers 200 within
--max-latency seconds and the API is still up afterwards. (An idle /widgets.json,
a 5 MB document built per request, already takes 1-2.5 s on a busy 4-CPU Mac.)
OECD is warmed first: its first call builds a ~1.5 GB metadata singleton in the
API process and pauses the loop once for 1.5-2.6 s, and OECD stays in process
by ruling (D8 Q5). Start it once the lane worker is up too (the API log shows
"Application startup complete" twice): its ~30 s import competes for the CPUs.
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

HEAVY = {
    'cftc_swap_trades_forex': '/api/v1/cftc/swap_trades?asset_class=forex&use_cache=true&provider=cftc',
    'finra_bonds_mbs': '/api/v1/finra/fixedincome/bonds?bond_type=MBS&include_matured=false&provider=finra',
    'oecd_list_dataflows': '/api/v1/oecd/list_dataflows',
    'tmx_covered_calls': '/api/v1/tmx/derivatives/options/covered_calls?premium_return_min=5&capital_gain_min=5&use_cache=true&provider=tmx',
}

parser = argparse.ArgumentParser()
parser.add_argument('base_url')
parser.add_argument('--rounds', type=int, default=1, help='run the heavy set this many times in a row')
parser.add_argument('--max-latency', type=float, default=5.0, help='seconds allowed per probe')
parser.add_argument('--only', nargs='*', choices=sorted(HEAVY), help='run just these heavy routes')
args = parser.parse_args()
base = args.base_url.rstrip('/')
heavy = {name: HEAVY[name] for name in args.only or HEAVY}


def get(path, timeout):
    started = time.monotonic()
    try:
        with urlopen(base + path, timeout=timeout) as response:
            size = len(response.read())
            return response.status, round(time.monotonic() - started, 2), size
    except Exception as error:  # an HTTP error status still means the server answered
        return getattr(error, 'code', type(error).__name__), round(time.monotonic() - started, 2), 0


def lanes():
    try:
        return json.load(urlopen(base + '/openbq/lanes', timeout=10))
    except Exception as error:
        return repr(error)


done, probes, t0 = threading.Event(), [], time.monotonic()


def probe():
    while not done.is_set():
        for path in ('/widgets.json', '/apps.json'):
            at = round(time.monotonic() - t0, 1)
            probes.append((path, *get(path, 30)[:2], at))
        time.sleep(1)


print(json.dumps({'oecd_warmup': get(HEAVY['oecd_list_dataflows'], 300)[:2], 'lanes_before': lanes()}))
poller = threading.Thread(target=probe)
poller.start()
rounds = []
for _ in range(args.rounds):
    with ThreadPoolExecutor(len(heavy)) as pool:
        results = dict(zip(heavy, pool.map(lambda path: get(path, 900), heavy.values())))
    rounds.append({name: {'status': s, 'seconds': t, 'bytes': b} for name, (s, t, b) in results.items()})
    print(json.dumps({'round': len(rounds), 'heavy': rounds[-1], 'lanes': lanes()}))
done.set()
poller.join()

times = sorted(t for _, s, t, _ in probes if s == 200)
failed = [p for p in probes if p[1] != 200]
slow = [p for p in probes if p[1] == 200 and p[2] > args.max_latency]
p99 = times[min(len(times) - 1, int(len(times) * 0.99))] if times else None
summary = {'probes': len(probes), 'probe_p99_seconds': p99, 'probe_max_seconds': times[-1] if times else None,
           'failed_probes': failed[:10], 'slow_probes': slow, 'api_up_after': get('/widgets.json', 30)[0]}
print(json.dumps(summary))
assert not failed and not slow and summary['api_up_after'] == 200, 'the API stalled'
print(json.dumps({'status': 'passed'}))
