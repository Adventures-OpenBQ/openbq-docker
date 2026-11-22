from datetime import datetime
import asyncio
import pytest
from app.day_charts import DayCharts, select_session, parse_symbols, approved_logo_url


def instant(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


@pytest.mark.parametrize('now,date,close,status', [
    ('2026-11-22T16:00:00Z','2026-11-20','21:00','closed'),
    ('2026-12-25T16:00:00Z','2026-12-24','18:00','closed'),
    ('2026-11-27T17:00:00Z','2026-11-27','18:00','open'),
    ('2026-11-27T19:00:00Z','2026-11-27','18:00','closed'),
    ('2026-11-23T13:00:00Z','2026-11-20','21:00','closed'),
])
def test_calendar(now,date,close,status):
    session, opened, closed, previous = select_session(instant(now))
    assert session['date'] == date
    assert closed.strftime('%H:%M') == close
    assert session['status'] == status
    assert previous < opened.date()


def test_input_and_logo_policy():
    assert parse_symbols(' AAPL,aapl.US,MSFT ') == ['AAPL', 'MSFT']
    with pytest.raises(ValueError):
        parse_symbols(','.join('A'+str(i) for i in range(21)))
    assert approved_logo_url('https://eodhd.com/img/logos/US/aapl.png')
    for bad in ['https://evil.test/a.png','https://eodhd.com@evil.test/a.png',
                'https://eodhd.com/api/a.png','https://eodhd.com/img/logos/a.svg',
                'https://eodhd.com/img/logos/a.png?api_token=x']:
        assert approved_logo_url(bad) is None


async def test_cold_history_same_session_basis_coalescing():
    calls = []
    async def history(symbol, interval, start, end, provider):
        assert len(start) == len(end) == 10  # OpenBB date-only request model
        calls.append((symbol, interval, start, end, provider))
        await asyncio.sleep(.001)
        if interval == '1d':
            return [{'date':'2026-11-19','close':100}, {'date':'2026-11-20','close':999}], {}
        return [{'date':'2026-11-20T14:29:00Z','close':90},
                {'date':'2026-11-20T14:30:00Z','close':101},
                {'date':'2026-11-20T20:59:00Z','close':105},
                {'date':'2026-11-20T21:01:00Z','close':999}], {}
    service = DayCharts(history, lambda s: {'name':'Apple','logo_url':None},
                        now=lambda: instant('2026-11-22T16:00:00Z'))
    a, b = await asyncio.gather(service.batch(['AAPL']), service.batch(['AAPL']))
    tile = a['tiles'][0]
    assert a == b
    assert len(calls) == 2
    assert tile['session']['date'] == '2026-11-20'
    assert tile['price'] == 105 and tile['previous_close'] == 100
    assert tile['change_percent'] == 5
    assert len(tile['points']) == 2 and tile['status'] == 'partial'
    assert tile['source'] == 'eodhd'
    assert 'cursor' not in str(tile['coverage'])
    assert all(c[-1] == 'eodhd' for c in calls)


async def test_failures_are_per_tile_and_unsupported_does_not_fetch():
    async def history(*args):
        raise RuntimeError('secret provider error')
    service = DayCharts(history, lambda s: {}, now=lambda: instant('2026-11-22T16:00:00Z'))
    tiles = (await service.batch(['AAPL','BTC-USD','BAD/URL']))['tiles']
    assert [t['status'] for t in tiles] == ['error']*3
    assert tiles[1]['error_code'] == 'unsupported_session'
    assert tiles[2]['error_code'] == 'invalid_symbol'
    assert 'secret' not in str(tiles)


async def test_empty_and_bounded_work():
    active = maximum = 0
    async def history(*args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(.002)
        active -= 1
        return [], {}
    service = DayCharts(history, lambda s: {}, now=lambda: instant('2026-11-22T16:00:00Z'))
    result = await service.batch(['A'+str(i) for i in range(20)])
    assert maximum <= 4
    assert all(t['status'] == 'empty' and t['price'] is None for t in result['tiles'])


def test_routes_and_widget(monkeypatch):
    from app.main import create_app
    from fastapi.testclient import TestClient
    import json
    from pathlib import Path
    monkeypatch.delenv('OPENBB_API_AUTH', raising=False)
    client = TestClient(create_app(api_key='test'))
    response = client.get('/day_charts?symbol=')
    assert response.status_code == 200
    assert response.json() == {'schema_version':1, 'tiles':[]}
    assert client.get('/day_charts', params={'symbol': ','.join('A'+str(i) for i in range(21))}).status_code == 422
    assert client.get('/symbol_logo?symbol=BTC-USD').status_code == 404
    widget = json.loads((Path(__file__).parents[1]/'widgets.json').read_text())['day_chart']
    assert widget['defaultRefresh'] == 15000
    assert widget['params'][0]['groupType'] == 'symbol'
    assert [p['paramName'] for p in widget['params'][1]] == ['rows','columns','scale','days','selected_symbol']
    assert client.get('/day_charts?days=6').status_code == 422


@pytest.mark.parametrize('status,headers,data,accepted', [
    (200, {'content-type':'image/png'}, b'\x89PNG\r\n\x1a\nabc', True),
    (302, {'location':'https://evil.test/a.png'}, b'', False),
    (200, {'content-type':'image/svg+xml'}, b'<svg/>', False),
    (200, {'content-type':'image/png'}, b'<svg/>', False),
    (200, {'content-type':'image/png'}, b'\x89PNG\r\n\x1a\n'+b'x'*262144, False),
])
async def test_logo_stream_rejects_unsafe_content(monkeypatch,status,headers,data,accepted):
    import httpx
    from app.day_charts import fetch_logo
    constructor = httpx.AsyncClient
    def handler(request):
        assert 'api_token' not in str(request.url)
        return httpx.Response(status, headers=headers, content=data)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: constructor(
        **kw, transport=httpx.MockTransport(handler)))
    if accepted:
        assert await fetch_logo('https://eodhd.com/img/logos/US/aapl.png') == (data,'image/png')
    else:
        with pytest.raises(ValueError):
            await fetch_logo('https://eodhd.com/img/logos/US/aapl.png')


async def test_bar_budget_and_missing_previous_close():
    async def too_many(*args):
        return [{}]*10001, {}
    service = DayCharts(too_many, lambda s: {}, now=lambda: instant('2026-11-22T16:00:00Z'))
    assert (await service.batch(['AAPL']))['tiles'][0]['error_code'] == 'history_budget'
    async def no_previous(symbol, interval, *args):
        return ([{'date':'2026-11-20T14:30:00Z','close':101}] if interval == '1m' else []), {}
    service = DayCharts(no_previous, lambda s: {}, now=lambda: instant('2026-11-22T16:00:00Z'))
    tile = (await service.batch(['AAPL']))['tiles'][0]
    assert tile['price'] == 101 and tile['previous_close'] is None
    assert tile['change'] is None and tile['status'] == 'partial'


async def test_logo_coalesces_and_caches(monkeypatch):
    from app import day_charts
    calls = 0
    async def fetch(url):
        nonlocal calls
        calls += 1
        await asyncio.sleep(.001)
        return b'png', 'image/png'
    monkeypatch.setattr(day_charts, 'fetch_logo', fetch)
    service = DayCharts(None, lambda s: {'logo_url':'https://eodhd.com/img/logos/US/a.png'})
    a, b = await asyncio.gather(service.logo('AAPL'), service.logo('AAPL'))
    assert a == b
    await service.logo('AAPL')
    assert calls == 1

async def test_two_trading_days_skip_weekend_clip_overnight_and_isolate_cache():
    async def history(symbol, interval, start, end, provider):
        if interval == '1d':
            return [{'date':'2026-11-18','close':90},{'date':'2026-11-19','close':100}], {}
        return [{'date':'2026-11-19T14:30:00Z','close':95},
                {'date':'2026-11-19T22:00:00Z','close':999},
                {'date':'2026-11-20T14:30:00Z','close':101}], {}
    service=DayCharts(history,lambda s:{},now=lambda:instant('2026-11-22T16:00:00Z'))
    t=(await service.batch(['AAPL'],days=2))['tiles'][0]
    assert [s['date'] for s in t['sessions']]==['2026-11-19','2026-11-20']
    assert [p['value'] for p in t['points']]==[95,101]
    assert t['chart_previous_close']==90
    assert [s['previous_close'] for s in t['sessions']]==[90,100]
    assert t['previous_close']==100 and t['change']==1
    one=(await service.batch(['AAPL']))['tiles'][0]
    assert len(one['points'])==1

async def test_closed_session_detail_has_real_ohlcv_and_calendar_bounds():
    calls=[]
    async def history(symbol,interval,start,end,provider):
        calls.append((symbol,interval,start,end,provider))
        return [{'date':'2026-11-20T14:29:00Z','open':1,'high':2,'low':1,'close':2,'volume':3},
                {'date':'2026-11-20T14:30:00Z','open':100,'high':103,'low':99,'close':102,'volume':5},
                {'date':'2026-11-20T14:31:00Z','open':102,'high':104,'low':101,'close':103,'volume':6},
                {'date':'2026-11-20T21:00:00Z','open':1,'high':2,'low':1,'close':2,'volume':3}],{}
    service=DayCharts(history,lambda s:{},now=lambda:instant('2026-11-22T16:00:00Z'))
    result=await service.closed_session('AAPL','5m')
    assert result['mode']=='closed' and result['source']=='eodhd'
    assert result['session']['date']=='2026-11-20'
    assert len(result['bars'])==1
    assert result['bars'][0]['open']==100 and result['bars'][0]['close']==103
    assert result['bars'][0]['volume']==11
    assert calls==[('AAPL','1m','2026-11-20','2026-11-20','eodhd')]
    await service.closed_session('AAPL','5m');assert len(calls)==1

async def test_open_and_crypto_do_not_query_closed_history():
    async def history(*args):raise AssertionError('must not fetch provider')
    service=DayCharts(history,lambda s:{},now=lambda:instant('2026-11-23T16:00:00Z'))
    assert (await service.closed_session('AAPL','1m'))['mode']=='stream'
    assert (await service.closed_session('BTC-USD','1m'))['mode']=='stream'
    service=DayCharts(history,lambda s:{},now=lambda:instant('2026-11-22T16:00:00Z'))
    assert (await service.closed_session('AAPL','1s'))['error_code']=='subminute_history_unavailable'

async def test_closed_session_early_close_and_missing_ohlcv_are_not_invented():
    calls=[]
    async def history(symbol,interval,start,end,provider):
        calls.append((start,end))
        return [{'date':'2026-12-24T14:30:00Z','open':100,'high':103,'low':99,'close':102,'volume':5},
                {'date':'2026-12-24T14:31:00Z','open':100,'high':103,'low':99,'close':102},
                {'date':'2026-12-24T18:01:00Z','open':100,'high':103,'low':99,'close':102,'volume':5}],{}
    service=DayCharts(history,lambda s:{},now=lambda:instant('2026-12-25T16:00:00Z'))
    result=await service.closed_session('AAPL','1m')
    assert calls==[('2026-12-24','2026-12-24')]
    assert result['session']['date']=='2026-12-24'
    assert len(result['bars'])==1 and result['partial']
