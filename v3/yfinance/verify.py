# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Build gate: real V5 discovery/query execution with the SDK boundary stubbed."""
import importlib.metadata as metadata
import pandas as pd
import yfinance as yf
from fastapi.testclient import TestClient
from openbb import obb
from openbb_core.api.rest_api import app
from openbb_platform_api.service.widgets_service import get_widgets_json
from openbq_yfinance.models import statements

assert metadata.version('openbb-core') == '2.0.1'
assert metadata.version('openbb-platform-api') == '2.0.1'
assert metadata.version('openbq-yfinance') == '3.0.0'
assert metadata.version('yfinance') == '1.7.0'
try:
    metadata.version('openbb-yfinance')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Conflicting legacy yfinance provider installed')

widgets = get_widgets_json(False, app.openapi(), [], app=app)
expected = ['yfinance_equity_historical_yfinance_obb', 'yfinance_fundamental_income_yfinance_obb', 'yfinance_fundamental_balance_yfinance_obb', 'yfinance_fundamental_cash_yfinance_obb']
assert all(k in widgets for k in expected)

seen = {}
def history(self, **kwargs):
    seen.update(kwargs)
    return pd.DataFrame({'Open':[10.], 'High':[12.], 'Low':[9.], 'Close':[11.], 'Adj Close':[10.5], 'Volume':[100]}, index=pd.DatetimeIndex(['2025-01-02'], tz='America/New_York'))
yf.Ticker.history = history
class Asset:
    def get_income_stmt(self, **kwargs):
        return pd.DataFrame({pd.Timestamp('2025-03-31'):[100., None]}, index=['Total Revenue', 'Interest Income'])
statements.ticker = lambda symbol: Asset()
client = TestClient(app)
r = client.get('/api/v1/yfinance/equity/historical', params={'symbol':'AAPL','start_date':'2025-01-01','end_date':'2025-01-03','auto_adjust':False})
assert r.status_code == 200, r.text
assert r.json()['results'][0]['adjusted_close'] == 10.5
assert r.json()['results'][0]['date'] == '2025-01-02', r.json()['results'][0]['date']
assert str(seen['end']) == '2025-01-04', seen  # inclusive end_date
r = client.get('/api/v1/yfinance/equity/historical', params={'symbol':'AAPL','start_date':'2025-01-02','end_date':'2025-01-02'})
assert r.status_code == 200, r.text
r = client.get('/api/v1/yfinance/fundamental/income', params={'symbol':'AAPL','period':'quarter','limit':12})
assert r.status_code == 200, r.text
assert r.json()['results'][0]['value'] == 100
assert r.json()['results'][1]['value'] is None
assert obb.yfinance.equity.historical(symbol='AAPL').results[0].close == 11
print('PASS: original yfinance V5 extension, four example widgets, historical prices and long-form statement/null handling')
