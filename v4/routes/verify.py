# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Build gate: both v4 routes through the real ODP app, Yahoo stubbed, exchange_calendars real."""
import importlib.metadata as metadata
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from openbb_core.api.rest_api import app
from openbb_platform_api.service.widgets_service import get_widgets_json
from openbq_routes import fundamentals

assert metadata.version('openbq-routes') == '4.0.0'
assert metadata.version('exchange_calendars') == '4.13.2'
client = TestClient(app)

r = client.get('/api/v1/calendar/trading', params={'exchange': 'XNYS', 'year': 2026})
assert r.status_code == 200, r.text
data = r.json()['data']
assert data['Timezone'] == 'America/New_York'
assert data['TradingHours'] == {'Open': '09:30:00', 'Close': '16:00:00', 'WorkingDays': 'Mon, Tue, Wed, Thu, Fri'}
holidays = data['ExchangeHolidays']
assert holidays['2026-07-03'] == {'Holiday': 'July 4th', 'Type': 'Official'}
assert holidays['2026-11-27'] == {'Holiday': 'Early close', 'Type': 'EarlyClose', 'EarlyClose': '13:00:00'}
assert holidays['2026-11-26']['Type'] == 'Official' and holidays['2026-12-24']['Type'] == 'EarlyClose'
assert sum(h['Type'] == 'Official' for h in holidays.values()) == 10
assert all(client.get('/api/v1/calendar/trading', params={'exchange': mic, 'year': 2026}).status_code == 200
           for mic in ['XLON', 'XTSE', 'XETR', 'XTKS', 'XHKG'])
tokyo = client.get('/api/v1/calendar/trading', params={'exchange': 'XTKS', 'year': 2026}).json()['data']
assert tokyo['TradingHours']['LunchBreakStart'] == '11:30:00' and tokyo['TradingHours']['Close'] == '15:30:00'
tokyo_2024 = client.get('/api/v1/calendar/trading', params={'exchange': 'XTKS', 'year': 2024}).json()['data']
assert tokyo_2024['TradingHours']['Close'] == '15:30:00', tokyo_2024['TradingHours']  # 15:00 until 2024-11-05
assert not any(h['Type'] == 'EarlyClose' for h in tokyo_2024['ExchangeHolidays'].values())
for params in [{'exchange': 'XXXX', 'year': 2026}, {'exchange': 'XNYS', 'year': 1989}, {'exchange': 'XTKS', 'year': 1991}]:
    assert client.get('/api/v1/calendar/trading', params=params).status_code == 404, params

year_end = {'AAPL': datetime(2025, 9, 27, tzinfo=timezone.utc).timestamp(),
            'HD': datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()}
fundamentals.ticker = lambda symbol: type('T', (), {'info': {'lastFiscalYearEnd': year_end[symbol]} if symbol in year_end else {}})()
for symbol, month in [('AAPL', 'September'), ('HD', 'January')]:
    r = client.get('/api/v1/fundamentals/fiscal_year_end', params={'symbol': symbol})
    assert r.status_code == 200 and r.json() == {'fiscalYearEnd': month}, r.text
assert client.get('/api/v1/fundamentals/fiscal_year_end', params={'symbol': 'NOTATICKER'}).status_code == 404

widgets = get_widgets_json(False, app.openapi(), [], app=app)
for key in ('calendar_trading_v1_calendars_custom_obb', 'calendar_trading_v1_bundle_custom_obb'):
    assert key not in widgets, f'calendar protocol endpoint leaked as widget: {key}'
assert widgets and not any('calendar_trading' in k or 'fiscal_year_end' in k for k in widgets), 'routes must not be widgets'
print('PASS: v4 calendar/trading (XNYS 2026, six MICs, 404s) and fundamentals/fiscal_year_end (AAPL September, 404)')
