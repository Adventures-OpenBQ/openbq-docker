#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Check BDOBB key-mode settings, dashboard and app sync on an OpenBQ API with OPENBB_API_AUTH on.

Usage: verify-settings.py BASE_URL USERNAME PASSWORD
Overwrites the credential's stored settings with a test object, then restores
what was there. Writes one test dashboard and one test app under fresh uuids,
then deletes both. On a credential with no dashboards yet, the first write
leaves a root folder behind.
"""
import base64
import json
import sys
import urllib.error
import urllib.request
import uuid

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

dash, app = str(uuid.uuid4()), str(uuid.uuid4())
content = {'index': dash, 'isFolder': False, 'data': {'name': 'verify-dashboards', 'widgets': [], 'gridLayout': {}}}
assert call('GET', '/pro/dash/sync/owned', auth=None)[0] == 401, 'missing key must be refused'
status, listed = call('GET', '/pro/dash/sync/owned')
assert status == 200 and isinstance(listed['owned'], dict), 'GET owned must return the map'
assert call('GET', '/pro/dash/sync/shared')[1] == {'shared': {}, 'entity_shared': {}}, 'shared must be empty'
assert call('POST', '/pro/dash/sync', {'items': {dash: content}})[1] == {'success': True}, 'POST must upsert'
stored = call('GET', '/pro/dash/sync/owned')[1]['owned'][dash]
assert stored['content']['data'] == content['data'] and stored['updated_date'], 'item must round-trip with a server date'
assert call('POST', '/pro/dash/sync', {'items': {dash: 3}})[0] == 400, 'a non-object item must be refused'
assert call('POST', '/pro/dash/sync', {'items': {dash: 'DELETE'}})[1] == {'success': True}, 'DELETE must succeed'
assert dash not in call('GET', '/pro/dash/sync/owned')[1]['owned'], 'a deleted item must be gone'
app_content = {'name': 'verify-dashboards', 'widgets': [], 'groups': [], 'gridLayout': {}}
assert call('POST', f'/pro/user-apps/{app}', app_content)[0] == 200, 'an app must upsert'
assert call('GET', '/pro/user-apps/sync')[1]['owned'][app]['content'] == app_content, 'the app must round-trip'
assert call('DELETE', f'/pro/user-apps/{app}')[0] == 200, 'the app must delete'
assert call('DELETE', f'/pro/user-apps/{app}')[0] == 404, 'a deleted app must be gone'
print(json.dumps({'dashboard_checks': 12, 'status': 'passed'}))
