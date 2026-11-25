"""Accepted review regressions; no provider/native calls."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import asyncio
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import main
from app.lake import series_with_lake

def row(t):
    return dict(date=t,open=100.,high=100.,low=100.,close=100.,volume=1.)

@pytest.mark.asyncio
async def test_lake_clips_timestamp_bounds_and_includes_date_end():
    class Lake:
        def wanted_days(self,*args): return [date(2026,11,23)]
        def read_day(self,*args):
            return pd.DataFrame({'time':[datetime(2026,11,23,h) for h in (10,12,13,16)],'price':[100.]*4,'size':[1.]*4})
    bars,_=await series_with_lake('AAPL','1m','2026-11-23T12:00:00Z','2026-11-23T13:00:00Z',None,timedelta(0),[],{},Lake(),today=date(2026,11,25))
    assert [b['date'].hour for b in bars]==[12,13]
    bars,_=await series_with_lake('AAPL','1m','2026-11-23','2026-11-23',None,timedelta(0),[],{},Lake(),today=date(2026,11,25))
    assert len(bars)==4

@pytest.mark.asyncio
async def test_tick_start_clips_to_first_fully_covered_bucket(monkeypatch):
    import openbq_kdb.aggregate as agg
    ticks=[row(datetime(2026,11,25,14,30)),row(datetime(2026,11,25,15,1)),row(datetime(2026,11,25,15,3))]
    async def history(*args): return ticks,{}
    monkeypatch.setattr(main,'fetch_history',history)
    monkeypatch.setattr(agg,'aggregate_ticks',lambda store,sym,interval,lo,hi:[r for r in ticks if lo<=r['date']<=hi])
    recorder=SimpleNamespace(store=SimpleNamespace(tick_span=lambda sym:(ticks[0]['date'],ticks[-1]['date'])))
    bars,_=await main.build_series('AAPL','1m','2026-11-25T15:00:30Z','2026-11-25T15:02:00Z',recorder,timedelta(days=2))
    assert [b['date'].minute for b in bars]==[1]

def test_socket_and_sector_share_account_cap(tmp_path,monkeypatch):
    monkeypatch.setenv('LIVE_GRID_CHART','false');monkeypatch.setenv('OPENBB_API_AUTH','false')
    monkeypatch.setenv('LIVE_GRID_MAX_SYMBOLS','2');monkeypatch.setenv('LIVE_GRID_WATCHLIST',str(tmp_path/'watchlist.json'))
    class Seed:
        def get_live_stock_prices(self,**kwargs): return dict(close=100,previousClose=99,volume=1)
    app=main.create_app(api_key='fixture',seed_client=Seed())
    client=TestClient(app)
    assert client.post('/api/subscriptions',json={'symbol':'NVDA'}).status_code==201
    assert client.post('/subscribe',json={'symbols':['MSFT']}).status_code==200
    with client.websocket_connect('/live_grid_ws') as ws:
        ws.send_json({'params':{'symbol':'AAPL'}})
        for _ in range(30):
            state=client.get('/api/subscriptions').json()
            if state['used']>2: break
        assert state['used']<=2
        with pytest.raises(WebSocketDisconnect): ws.receive_json()
    assert client.get('/api/subscriptions').json()['used']==2
    assert client.get('/sector_map').status_code==507
    with client.websocket_connect('/live_grid_ws') as ws:
        ws.send_json({'params':{'symbol':'NVDA'}})
        # A later HTTP request observes accepted registration on the same loop.
        assert client.get('/api/subscriptions').json()['used']==2
        ws.send_json({'params':{'symbol':'MSFT'}})
        assert client.get('/api/subscriptions').json()['used']==2


def test_socket_replacement_releases_only_its_old_account_symbols(tmp_path,monkeypatch):
    monkeypatch.setenv('LIVE_GRID_CHART','false');monkeypatch.setenv('OPENBB_API_AUTH','false')
    monkeypatch.setenv('LIVE_GRID_MAX_SYMBOLS','3');monkeypatch.setenv('LIVE_GRID_WATCHLIST',str(tmp_path/'watchlist.json'))
    class Seed:
        def get_live_stock_prices(self,**kwargs): return dict(close=100,previousClose=99,volume=1)
    app=main.create_app(api_key='fixture',seed_client=Seed())
    client=TestClient(app)  # no lifespan/feed loop, no provider connection
    def observed(symbol):
        for _ in range(100):
            client.get('/api/subscriptions')
            if symbol in app.state.manager._union('us'):return
        pytest.fail(f'{symbol} was never admitted')
    client.post('/api/subscriptions',json={'symbol':'NVDA'})
    client.post('/subscribe',json={'symbols':['MSFT']})
    with client.websocket_connect('/live_grid_ws') as first:
        first.send_json({'params':{'symbol':'AAPL'}});observed('AAPL')
        with client.websocket_connect('/live_grid_ws') as second:
            second.send_json({'params':{'symbol':'GOOG'}})
            with pytest.raises(WebSocketDisconnect):second.receive_json()
        assert client.post('/subscribe',json={'symbols':['GOOG']}).status_code==507
        assert client.post('/api/subscriptions',json={'symbol':'GOOG'}).status_code==507
        first.send_json({'params':{'symbol':'TSLA'}});observed('TSLA')
        assert app.state.manager._union('us')=={'NVDA','MSFT','TSLA'}
    assert client.post('/api/subscriptions',json={'symbol':'GOOG'}).status_code==201

@pytest.mark.asyncio
async def test_lake_end_clips_trades_inside_the_final_bucket():
    class Lake:
        def wanted_days(self,*args):return [date(2026,11,23)]
        def read_day(self,*args):
            return pd.DataFrame({'time':[datetime(2026,11,23,12),datetime(2026,11,23,12,0,45)],'price':[100.,999.],'size':[1.,1.]})
    bars,_=await series_with_lake('AAPL','1m','2026-11-23T12:00:00Z','2026-11-23T12:00:30Z',None,timedelta(0),[],{},Lake(),today=date(2026,11,25))
    assert len(bars)==1 and bars[0]['close']==100. and bars[0]['volume']==1.
