#!/usr/bin/env python3
"""Check the v4 BDOBB routes on a running OpenBQ API (live Yahoo for AAPL).

Usage: verify-v4-routes.py BASE_URL [USERNAME PASSWORD]
Pass the API's Basic credential when OPENBB_API_AUTH is on.
"""
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

base = sys.argv[1].rstrip('/')
headers = {}
if len(sys.argv) == 4:
    headers['Authorization'] = 'Basic ' + base64.b64encode(f'{sys.argv[2]}:{sys.argv[3]}'.encode()).decode()


def get(path, **params):
    url = base + path + ('?' + urllib.parse.urlencode(params) if params else '')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


status, body = get('/api/v1/calendar/trading', exchange='XNYS', year=2026)
assert status == 200, status
data = body['data']
assert data['Timezone'] == 'America/New_York' and data['TradingHours']['Open'] == '09:30:00'
assert data['ExchangeHolidays']['2026-07-03']['Type'] == 'Official', 'July 3 2026 must be closed'
assert data['ExchangeHolidays']['2026-11-27'] == {'Holiday': 'Early close', 'Type': 'EarlyClose', 'EarlyClose': '13:00:00'}
for mic in ['XLON', 'XTSE', 'XETR', 'XTKS', 'XHKG']:
    assert get('/api/v1/calendar/trading', exchange=mic, year=2026)[0] == 200, mic
assert get('/api/v1/calendar/trading', exchange='XXXX', year=2026)[0] == 404, 'unknown MIC must be 404'
assert get('/api/v1/fundamentals/fiscal_year_end', symbol='AAPL') == (200, {'fiscalYearEnd': 'September'})
assert get('/api/v1/fundamentals/fiscal_year_end', symbol='NOTATICKER')[0] == 404, 'unknown symbol must be 404'
status, widgets = get('/widgets.json')
assert status == 200 and widgets and not any('fiscal_year_end' in k or 'calendar_trading' in k for k in widgets)
print('PASS: calendar/trading, fundamentals/fiscal_year_end and widgets.json on', base)
