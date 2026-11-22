# Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Bounded provider-history US regular-session snapshots; never a q tape cursor."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo
import json
import inspect
import math
import re
import time
from urllib.parse import urlsplit

import exchange_calendars as xcals
from app.classify import classify, normalize
from app.market_time import naive_utc, wire_time

MAX_LOGO = 256 * 1024


def parse_symbols(raw):
    if len(raw) > 2048:
        raise ValueError('symbol input too long')
    values = list(dict.fromkeys(normalize(s) or s.strip().upper()
                               for s in raw.split(',') if s.strip()))
    if len(values) > 20:
        raise ValueError('maximum 20 unique symbols')
    return values


@lru_cache(maxsize=4)
def calendar(year):
    return xcals.get_calendar('XNYS', start=f'{year-1}-01-01', end=f'{year+1}-12-31')


def select_session(now):
    cal = calendar(now.year)
    day = now.astimezone(ZoneInfo('America/New_York')).date()
    session = cal.date_to_session(str(day), direction='previous')
    if now < cal.session_open(session).to_pydatetime():
        session = cal.previous_session(session)
    opened = cal.session_open(session).to_pydatetime()
    closed = cal.session_close(session).to_pydatetime()
    return ({'date': str(session.date()), 'timezone': 'America/New_York',
             'label': 'US regular session', 'status': 'open' if opened <= now < closed
             else 'closed'}, opened, closed, cal.previous_session(session).date())


def approved_logo_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'eodhd.com' or parsed.query
            or parsed.fragment or not re.fullmatch(
                r'/img/logos/[A-Za-z0-9_./-]+\.(?:png|jpg|jpeg|webp|gif)', parsed.path)
            or '..' in parsed.path):
        return None
    return value


def raster_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


async def fetch_logo(url):
    import httpx
    if not approved_logo_url(url):
        raise ValueError('unapproved logo')
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
        async with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise ValueError('logo unavailable')
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > MAX_LOGO:
                    raise ValueError('logo too large')
            mime = raster_type(chunks)
            if not mime or response.headers.get('content-type', '').split(';')[0] != mime:
                raise ValueError('invalid logo type')
            return bytes(chunks), mime


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


class DayCharts:
    def __init__(self, history, metadata, *, now=None):
        self.history = history
        self.metadata = metadata
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.cache = OrderedDict()
        self.pending = {}
        self.work = asyncio.Semaphore(4)
        self.logos = OrderedDict()
        self.logo_pending = {}

    async def batch(self, symbols, days=1):
        if not isinstance(days, int) or not 1 <= days <= 5:
            raise ValueError("trading days must be 1 to 5")
        async def tile(symbol):
            key = (symbol, days)
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            if key not in self.pending:
                if len(self.pending) >= 128:
                    return self.blank(symbol, 'busy')
                self.pending[key] = asyncio.create_task(self.load(symbol, days))
            return await asyncio.shield(self.pending[key])
        async with asyncio.timeout(20):
            results = await asyncio.gather(*(tile(s) for s in symbols))
        payload = {'schema_version': 1, 'tiles': results}
        if len(json.dumps(payload, allow_nan=False).encode()) > 2 * 1024 * 1024:
            raise ValueError('response too large')
        return payload

    @staticmethod
    def blank(symbol, error=None):
        tile = dict(symbol=symbol, name=None, logo_path=None,
                    session=dict(date=None, timezone='America/New_York', label='US regular session',
                                 status='unknown'), previous_close=None, price=None, change=None,
                    change_percent=None, points=[], as_of=None, status='empty',
                    source='eodhd', coverage={'first_bar': None, 'last_bar': None,
                                               'partial': True, 'bar_count': 0})
        if error:
            tile.update(status='error', error_code=error)
        return tile

    async def load(self, symbol, days=1):
        result = self.blank(symbol)
        try:
            async with asyncio.timeout(19):
                async with self.work:
                    if normalize(symbol) != symbol:
                        result = self.blank(symbol, 'invalid_symbol')
                    elif classify(symbol) not in ('us', 'crypto'):
                        result = self.blank(symbol, 'unsupported_session')
                    else:
                        result = await self.snapshot(symbol, days)
        except TimeoutError:
            result = self.blank(symbol, 'provider_timeout')
        except Exception:
            result = self.blank(symbol, 'provider_error')
        finally:
            self.pending.pop((symbol, days), None)
        self.cache[(symbol, days)] = (time.monotonic() + 15, result)
        while len(self.cache) > 256:
            self.cache.popitem(last=False)
        return result

    async def snapshot(self, symbol, days=1):
        now = self.now()
        crypto = classify(symbol) == 'crypto'
        if crypto:
            opened = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            closed = opened + timedelta(days=1)
            session = dict(date=str(opened.date()), timezone='UTC', label='Crypto UTC day', status='open')
            latest_previous = opened.date() - timedelta(days=1)
            sessions = [(dict(date=str((opened-timedelta(days=i)).date()), timezone='UTC',
                              label='Crypto UTC day', status='open' if i == 0 else 'closed'),
                         opened-timedelta(days=i), closed-timedelta(days=i))
                        for i in reversed(range(days))]
            previous = sessions[0][1].date() - timedelta(days=1)
            cal = None
        else:
            session, opened, closed, previous = select_session(now)
            cal = calendar(now.year)
            latest_previous = previous
            sessions = [(session, opened, closed)]
            for _ in range(days - 1):
                label = cal.date_to_session(str(previous))
                start = cal.session_open(label).to_pydatetime()
                end = cal.session_close(label).to_pydatetime()
                sessions.insert(0, (dict(date=str(label.date()), timezone='America/New_York',
                                         label='US regular session', status='closed'), start, end))
                previous = cal.previous_session(label).date()
        bars, history_meta = await self.history(symbol, '1m', str(sessions[0][1].date()),
                                     str(min(now, closed).date()), 'eodhd')
        daily, _ = await self.history(symbol, '1d', str(previous), str(latest_previous), 'eodhd')
        if len(bars) > 10000 or len(daily) > 10000:
            return self.blank(symbol, 'history_budget')
        points = {}
        for row in bars:
            try:
                at = naive_utc(row.get('date')).replace(tzinfo=timezone.utc)
                value = number(row.get('close'))
                if any(start <= at < min(now, end) for _, start, end in sessions) and value is not None:
                    points[wire_time(at)] = value
            except (ValueError, TypeError):
                continue
        ordered = [dict(time=t, value=v) for t, v in sorted(points.items())]
        tile = self.blank(symbol)
        if crypto and history_meta.get('rows_from_ticks', 0) > 0:
            tile['source'] = 'eodhd+kdb ticks'
        if crypto and history_meta.get('rows_from_coinbase', 0) > 0:
            tile['source'] += '+coinbase'
        tile.update(session=session, points=ordered,
                    sessions=[dict(**info, opened=wire_time(start), closed=wire_time(end),
                                   previous_close=next((number(row.get('close')) for row in daily
                                     if str(row.get('date'))[:10] == str(datetime.fromisoformat(info['date']).date()-timedelta(days=1) if crypto else
                                         cal.previous_session(cal.date_to_session(info['date'])).date())), None))
                              for info, start, end in sessions])
        tile['chart_previous_close'] = next((number(row.get('close')) for row in daily
                                             if str(row.get('date'))[:10] == str(previous)), None)
        previous_close = next((number(row.get('close')) for row in daily
                               if str(row.get('date'))[:10] == str(latest_previous)), None)
        tile['previous_close'] = previous_close
        if ordered:
            tile['price'] = ordered[-1]['value']
            tile['as_of'] = ordered[-1]['time']
            if previous_close is not None:
                tile['change'] = tile['price'] - previous_close
                tile['change_percent'] = tile['change'] / previous_close * 100 if previous_close else None
            expected = sum(max(0, int((min(now, end) - start).total_seconds() // 60))
                           for _, start, end in sessions)
            partial = (len(ordered) < expected or previous_close is None
                       or any(s['previous_close'] is None for s in tile['sessions']))
            tile['status'] = 'partial' if partial else 'ok'
            tile['coverage'] = dict(first_bar=ordered[0]['time'], last_bar=ordered[-1]['time'],
                                    bar_count=len(ordered), partial=partial)
        try:
            meta = self.metadata(symbol)
            if inspect.isawaitable(meta):
                meta = await asyncio.wait_for(meta, timeout=3)
            tile['name'] = meta.get('name')
            if approved_logo_url(meta.get('logo_url')):
                tile['logo_path'] = '/symbol_logo?symbol=' + symbol
        except Exception:
            pass
        return tile

    async def closed_session(self, symbol, interval):
        if classify(symbol) != 'us':
            return dict(schema_version=1, mode='stream', symbol=symbol, interval=interval, bars=[])
        now = self.now()
        info, opened, closed, _ = select_session(now)
        base = dict(schema_version=1, symbol=symbol, interval=interval, session=info,
                    source='eodhd', bars=[])
        if info['status'] == 'open':
            return dict(base, mode='stream')
        if interval == '1s':
            return dict(base, mode='closed', error_code='subminute_history_unavailable')
        key = ('closed', symbol, interval, info['date'])
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if key not in self.pending:
            if len(self.pending) >= 128:
                raise ValueError('history busy')
            self.pending[key] = asyncio.create_task(self._closed_session(key, base, opened, closed))
        return await asyncio.shield(self.pending[key])

    async def _closed_session(self, key, base, opened, closed):
        from app.series import resample
        try:
            async with asyncio.timeout(19):
                async with self.work:
                    rows, _ = await self.history(base['symbol'], '1m', str(opened.date()),
                                                 str(closed.date()), 'eodhd')
                    if len(rows) > 10000:
                        raise ValueError('history budget')
                    clean = {}
                    for row in rows:
                        try:
                            at = naive_utc(row.get('date')).replace(tzinfo=timezone.utc)
                            values = {k: number(row.get(k)) for k in ('open','high','low','close','volume')}
                            if not opened <= at < closed or any(v is None for v in values.values()):
                                continue
                            if (values['volume'] < 0 or values['low'] > min(values['open'],values['close'])
                                    or values['high'] < max(values['open'],values['close'])):
                                continue
                            clean[wire_time(at)] = dict(date=wire_time(at), **values)
                        except (ValueError, TypeError):
                            continue
                    bars = [clean[t] for t in sorted(clean)]
                    partial = len(bars) < int((closed-opened).total_seconds()//60)
                    if base['interval'] != '1m':
                        bars = resample(bars, base['interval'])
                    result = dict(base, mode='closed', bars=bars, partial=partial)
                    if len(json.dumps(result, allow_nan=False)) > 512*1024:
                        raise ValueError('history response budget')
                    self.cache[key] = (time.monotonic()+15, result)
                    while len(self.cache)>256:
                        self.cache.popitem(last=False)
                    return result
        finally:
            self.pending.pop(key, None)

    async def logo(self, symbol):
        cached = self.logos.get(symbol)
        if cached and cached[0] > time.monotonic():
            if cached[1] is None:
                raise ValueError('logo unavailable')
            return cached[1]
        if symbol not in self.logo_pending:
            if len(self.logo_pending) >= 64:
                raise ValueError('logo busy')
            self.logo_pending[symbol] = asyncio.create_task(self.load_logo(symbol))
        return await asyncio.shield(self.logo_pending[symbol])

    async def load_logo(self, symbol):
        result = None
        try:
            async with asyncio.timeout(10):
                async with self.work:
                    meta = self.metadata(symbol)
                    if inspect.isawaitable(meta):
                        meta = await meta
                    result = await fetch_logo(meta.get('logo_url'))
            return result
        except Exception:
            raise ValueError('logo unavailable') from None
        finally:
            self.logo_pending.pop(symbol, None)
            self.logos[symbol] = (time.monotonic() + (3600 if result else 60), result)
            while len(self.logos) > 64:
                self.logos.popitem(last=False)


async def provider_metadata(symbol, key):
    """Same filtered EODHD fundamentals metadata as symbol_meta, with async timeout."""
    if classify(symbol) == 'crypto':
        return {'name': 'Bitcoin' if symbol == 'BTC-USD' else symbol, 'logo_url': None}
    import httpx
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f'https://eodhd.com/api/fundamentals/{symbol}.US',
                                    params={'api_token': key, 'fmt': 'json',
                                            'filter': 'General::LogoURL,General::Name'})
        response.raise_for_status()
        payload = response.json()
    logo = payload.get('General::LogoURL')
    if isinstance(logo, str) and logo.startswith('/'):
        logo = 'https://eodhd.com' + logo
    name = payload.get('General::Name')
    return {'name': name[:256] if isinstance(name, str) else None, 'logo_url': logo}
