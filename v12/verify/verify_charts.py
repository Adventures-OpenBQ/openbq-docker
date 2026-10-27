# v12/verify/verify_charts.py
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Run inside openbq-arts-charts:12.0.0 on the verify project's bridge (verify-charts.sh).
Every check runs through the gateway door (G) and, where the door is not the point, directly
against arts-charts with the stack pair (D: what svc:openbq-charts proxies to)."""
import json
import os
import queue
import socket
import threading
import time
from urllib.parse import urlsplit

import httpx
from websockets.sync.client import connect

from arts_charts.tokens import sign

E = os.environ
ORIGIN, GW = E['CHARTS_ORIGIN'], E['CHARTS_GATEWAY']  # the door origin (set by verify-charts.sh), the gateway on the bridge
HOST = urlsplit(ORIGIN).netloc
BEARER = {'Authorization': 'Bearer ' + E['GATEWAY_TOKEN'], 'Host': HOST}
PAIR = (E['OPENBB_API_USERNAME'], E['OPENBB_API_PASSWORD'])
DIRECT = 'http://arts-charts:8000'
NTFY = (E['NTFY_USER'], E['NTFY_PASS'])
TOPIC = E['ARTS_CHARTS_NTFY_TOPIC']
BODY = {'schema': 'chart/1', 'symbol': 'AAPL', 'interval': '1d',
        'series': [{'type': 'candlestick', 'panel': 1, 'side': 'right'}]}
g = httpx.Client(base_url=GW, headers=BEARER, timeout=150)
anon = httpx.Client(base_url=GW, headers={'Host': HOST}, timeout=150)
d = httpx.Client(base_url=DIRECT, auth=PAIR, timeout=150)


def check(name, ok):
    print(('PASS ' if ok else 'FAIL ') + name, flush=True)
    if not ok:
        raise SystemExit(1)


for _ in range(60):  # arts-charts migrates, then serves
    try:
        if d.get('/ta_registry').status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(2)
for client, door in ((g, 'G'), (d, 'D')):
    check(f'{door} /ta_registry', client.get('/ta_registry').status_code == 200)

events = queue.Queue()
def feed():
    with g.stream('GET', '/charts/events', timeout=None) as response:
        for line in response.iter_lines():
            if line.startswith('data: '):
                events.put(json.loads(line[6:]))
threading.Thread(target=feed, daemon=True).start()
time.sleep(1)

made = g.post('/charts', json={'title': 'Verify', 'body': BODY})
if made.status_code != 201:
    print(made.status_code, made.text[:300], flush=True)
check('G POST /charts', made.status_code == 201)
chart = made.json()['id']
check('G GET /charts/{id}', g.get(f'/charts/{chart}').json()['revision'] == 1)
saved = g.put(f'/charts/{chart}', json={'title': 'Verify 2', 'body': BODY}, headers={'If-Match': '1'})
check('G PUT /charts/{id}', saved.status_code == 200 and saved.json()['revision'] == 2)
check('G stale PUT is 409 with the document', g.put(f'/charts/{chart}', json={'title': 'x', 'body': BODY},
      headers={'If-Match': '1'}).json().get('revision') == 2)
deadline = time.time() + 20
seen = False
while time.time() < deadline and not seen:
    try:
        seen = events.get(timeout=1).get('id') == chart
    except queue.Empty:
        pass
check('G change feed event', seen)

for client, door in ((g, 'G'), (d, 'D')):
    rpc = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18'}
    client.post('/charts/mcp', headers=rpc, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'verify', 'version': '1'}}})
    tools = client.post('/charts/mcp', headers=rpc, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).json()
    check(f'{door} /charts/mcp tools/list', any(t['name'] == 'describe_chart' for t in tools['result']['tools']))
    png = client.get(f'/charts/{chart}/snapshot.png')
    if png.status_code != 200:
        print(png.status_code, png.text[:300], flush=True)
    check(f'{door} snapshot.png', png.status_code == 200 and png.content[:4] == b'\x89PNG')

with connect(f'ws://{HOST}/ta_series_ws?symbol=AAPL&interval=1d', sock=socket.create_connection((urlsplit(GW).hostname, urlsplit(GW).port)),
             additional_headers={'Authorization': BEARER['Authorization'], 'Origin': ORIGIN}, max_size=8 * 2**20) as ws:
    check('G /ta_series_ws first frame', json.loads(ws.recv(timeout=60))['type'] == 'series')
import base64
with connect('ws://arts-charts:8000/ta_series_ws?symbol=AAPL&interval=1d', max_size=8 * 2**20,
             additional_headers={'Authorization': 'Basic ' + base64.b64encode(':'.join(PAIR).encode()).decode()}) as ws:
    check('D /ta_series_ws first frame', json.loads(ws.recv(timeout=60))['type'] == 'series')

pushes = queue.Queue()
def subscribe(base, **kw):
    with httpx.Client(timeout=None, **kw) as c, c.stream('GET', base, auth=NTFY) as response:
        for line in response.iter_lines():
            message = json.loads(line)
            if message.get('event') == 'message':
                pushes.put((base, message))
threading.Thread(target=subscribe, args=(f'{GW}/ntfy/{TOPIC}/json',), kwargs={'headers': {'Host': HOST}}, daemon=True).start()
threading.Thread(target=subscribe, args=(f'http://ntfy:2586/{TOPIC}/json',), daemon=True).start()
time.sleep(2)

watch = d.post('/watches', json={'chart_id': chart, 'condition': 'close > 1'}).json()['id']
action = sign(E['ARTS_CHARTS_SECRET'], 'action', 600, watch=watch, action='snapshot')
pressed = anon.post('/watches/action', json={'token': action})
check('G POST /watches/action without the gateway token', pressed.status_code == 200)
forged_action = anon.post('/watches/action', json={'token': action[:-4] + 'AAAA'})
check('G forged action token is 401', forged_action.status_code == 401)
got = {}
deadline = time.time() + 150
while time.time() < deadline and len(got) < 2:
    try:
        base, message = pushes.get(timeout=5)
    except queue.Empty:
        continue
    if 'attachment' in message:  # the push that carries the picture, not an earlier plain alert
        got[base] = message
check('ntfy push with a picture received through the door and directly', len(got) == 2)
for base, message in got.items():
    link = urlsplit(message['attachment']['url'])  # ntfy reports a published attach as attachment.url
    check(f'push link uses ARTS_CHARTS_PUBLIC_URL ({'door' if base.startswith(GW) else 'direct'})', f'{link.scheme}://{link.netloc}' == ORIGIN)
picture = anon.get(link.path + '?' + link.query)
check('G link-token PNG without the gateway token', picture.status_code == 200 and picture.content[:4] == b'\x89PNG')
item_path = link.path.rsplit('/snapshots/', 1)[0]
check('G link-token inbox item', anon.get(item_path + '?' + link.query).status_code == 200)
forged_path = item_path + '?t=' + link.query[2:-4] + 'AAAA'
# arts-charts answers a forged link token 401 with an empty body; on a token-only route the door relays it as 401.
check('D forged link token is 401', httpx.get(DIRECT + forged_path, timeout=60).status_code == 401)
check('G forged link token is 401', anon.get(forged_path).status_code == 401)
check('G no token is 401', anon.get('/charts').status_code == 401)
check('G trailing slash is 404', g.get('/charts/').status_code == 404)
print('verify-charts: all checks passed')
