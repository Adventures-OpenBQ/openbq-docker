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
assert metadata.version('yfinance') == '1.8.0'
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
    nan = float('nan')
    return pd.DataFrame({'Open':[10., nan], 'High':[12., nan], 'Low':[9., nan], 'Close':[11., nan], 'Adj Close':[10.5, nan], 'Volume':[100, 0]}, index=pd.DatetimeIndex(['2025-01-02', '2025-01-03'], tz='America/New_York'))
yf.Ticker.history = history
class Asset:
    def get_income_stmt(self, **kwargs):
        return pd.DataFrame({pd.Timestamp('2025-03-31'):[100., None]}, index=['Total Revenue', 'Interest Income'])
statements.ticker = lambda symbol: Asset()
client = TestClient(app)
r = client.get('/api/v1/yfinance/equity/historical', params={'symbol':'AAPL','start_date':'2025-01-01','end_date':'2025-01-03','auto_adjust':False})
assert r.status_code == 200, r.text
assert r.json()['results'][0]['adjusted_close'] == 10.5
assert len(r.json()['results']) == 1, 'placeholder bar with no prices must be skipped'
assert r.json()['results'][0]['date'] == '2025-01-02', r.json()['results'][0]['date']
assert str(seen['end']) == '2025-01-04', seen  # inclusive end_date
r = client.get('/api/v1/yfinance/equity/historical', params={'symbol':'AAPL','start_date':'2025-01-02','end_date':'2025-01-02'})
assert r.status_code == 200, r.text
r = client.get('/api/v1/yfinance/fundamental/income', params={'symbol':'AAPL','period':'quarter','limit':12})
assert r.status_code == 200, r.text
assert r.json()['results'][0]['value'] == 100
assert r.json()['results'][1]['value'] is None
assert obb.yfinance.equity.historical(symbol='AAPL').results[0].close == 11
assert 'yfinance_options_chains_long_yfinance_obb' in widgets
from types import SimpleNamespace
from openbq_yfinance.models import options
class Chain:
    options = ('2025-01-17', '2025-02-21')
    def option_chain(self, expiration):
        frame = pd.DataFrame([{'contractSymbol': 'C' + expiration, 'strike': 100, 'impliedVolatility': .25}])
        return SimpleNamespace(calls=frame, puts=frame, underlying={'regularMarketPrice': 101., 'regularMarketTime': 1735851600, 'exchangeTimezoneName': 'America/New_York'})
options.ticker = lambda symbol: Chain()
r = client.get('/api/v1/yfinance/options/chains_long', params={'symbol':'AAPL'})
assert r.status_code == 200, r.text
rows = r.json()['results']
assert [(x['expiration'], x['option_type'], x['dte']) for x in rows] == [('2025-01-17','call',15), ('2025-01-17','put',15), ('2025-02-21','call',50), ('2025-02-21','put',50)], rows
assert {(x['underlying_symbol'], x['eod_date'], x['underlying_price'], x['implied_volatility']) for x in rows} == {('AAPL', '2025-01-02', 101., .25)}, rows
print('PASS: original yfinance V5 extension, four example widgets, historical prices and long-form statement/null handling')
