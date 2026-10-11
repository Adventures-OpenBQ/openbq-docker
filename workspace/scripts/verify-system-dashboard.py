#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Check BDOBB's hidden docks dashboard on a Workspace/Lite built with patch 004 (login mode).

Usage: verify-system-dashboard.py BACKEND_URL EMAIL PASSWORD
BACKEND_URL is the backend root BDOBB signs in to (Lite: https://HOST/api). Signs in with
POST /pro/login as BDOBB does, then checks /pro/dash/sync/system/docks. The docks is written
and deleted only when the account has none; an existing one is read, never overwritten.
"""
import json
import sys
import urllib.error
import urllib.request

base, email, password = sys.argv[1].rstrip('/'), sys.argv[2], sys.argv[3]
token = None


def call(method, path, body=None, auth=True):
    headers = {'Content-Type': 'application/json'}
    if auth:
        headers['Authorization'] = f'Bearer {token}'
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        text = error.read()
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, None


status, login = call('POST', '/pro/login', {'email': email, 'password': password, 'remember': False, 'source': 'pro'},
                     auth=False)
assert status == 200 and login.get('access_token'), 'sign-in must succeed'
token = login['access_token']
docks = '/pro/dash/sync/system/docks'
assert call('GET', docks, auth=False)[0] in (401, 403), 'a missing token must be refused'
assert call('GET', '/pro/dash/sync/system/other')[0] == 404, 'only reserved ids exist'
status, current = call('GET', docks)
assert status == 200 and 'dashboard' in current, 'GET docks must answer {dashboard}'
checks = 4
if current['dashboard'] is None:
    content = {'id': 'docks', 'name': 'verify-system-dashboard', 'hidden': True, 'tabs': []}
    status, put = call('PUT', docks, {'revision': 2, 'content': content})
    assert status == 200 and put['dashboard']['hidden'] is True and put['dashboard']['content'] == content, 'PUT must store'
    assert call('GET', docks)[1]['dashboard']['revision'] == 2, 'GET must return the stored revision'
    owned = call('GET', '/pro/dash/sync/owned')[1]['owned']
    assert not any(v.get('content') == content for v in owned.values()), 'the owned list must not show the docks'
    complete = call('GET', '/pro/dash/sync')[1]
    assert not any(v.get('content') == content for v in complete['owned'].values()), 'the full sync must not show it'
    assert call('PUT', docks, {'revision': 1, 'content': content})[0] == 409, 'an older PUT must lose'
    assert call('PUT', docks, {'revision': 2, 'content': content, 'x': 1})[0] == 400, 'extra keys must be refused'
    assert call('DELETE', docks + '?revision=1')[0] == 409, 'an older DELETE must lose'
    assert call('DELETE', docks)[0] == 400, 'DELETE must carry a revision'
    assert call('DELETE', docks + '?revision=2')[1] == {'success': True}, 'DELETE must succeed'
    assert call('GET', docks)[1] == {'dashboard': None}, 'a deleted docks must be gone'
    checks += 10
print(json.dumps({'system_dashboard_checks': checks, 'status': 'passed'}))
