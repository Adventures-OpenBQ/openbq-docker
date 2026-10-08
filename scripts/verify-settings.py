#!/usr/bin/env python3
"""Check BDOBB key-mode settings on an OpenBQ API with OPENBB_API_AUTH on.

Usage: verify-settings.py BASE_URL USERNAME PASSWORD
Overwrites the credential's stored settings with a test object, then restores
what was there.
"""
import base64
import json
import sys
import urllib.error
import urllib.request

base, user, password = sys.argv[1].rstrip('/'), sys.argv[2], sys.argv[3]


def call(method, path, body=None, auth=(user, password)):
    headers = {'Content-Type': 'application/json'}
    if auth:
        headers['Authorization'] = 'Basic ' + base64.b64encode(f'{auth[0]}:{auth[1]}'.encode()).decode()
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


assert call('GET', '/pro/user', auth=None)[0] == 401, 'missing key must be refused'
assert call('GET', '/pro/user', auth=(user, password + 'x'))[0] == 401, 'wrong key must be refused'
assert call('POST', '/pro/display-settings', {'a': 1}, auth=None)[0] == 401, 'missing key must not write'
status, before = call('GET', '/pro/user')
assert status == 200 and isinstance(before['pro_display_settings'], dict), 'GET /pro/user must return the object'
sample = {'theme': 'dark', 'extensions': {'bdobb': {'v': 3, 'nested': [1, {'x': None}]}}, 'unknown_key': True}
assert call('POST', '/pro/display-settings', sample)[0] // 100 == 2, 'POST must store the object'
assert call('GET', '/pro/user')[1]['pro_display_settings'] == sample, 'stored object must round-trip unchanged'
assert call('POST', '/pro/display-settings', b'[1, 2]')[0] == 400, 'a non-object body must be refused'
assert call('GET', '/pro/user')[1]['pro_display_settings'] == sample, 'a refused write must not change the object'
call('POST', '/pro/display-settings', before['pro_display_settings'])
print(json.dumps({'settings_checks': 8, 'status': 'passed'}))
