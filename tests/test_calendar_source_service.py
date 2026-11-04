# SPDX-License-Identifier: Apache-2.0
"""Bounded source service policy, independent of a database or upstream provider."""
import importlib.util
from pathlib import Path
import pytest


def implementation():
    path=Path(__file__).resolve().parents[1]/'v11/calendar-source/service.py'
    spec=importlib.util.spec_from_file_location('calendar_source_service',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_or_weak_configuration_and_arbitrary_upstreams_are_refused():
    module=implementation()
    for env in [{},{'CALENDAR_SOURCE_USER':'u','CALENDAR_SOURCE_PASSWORD':'short'},
                {'CALENDAR_SOURCE_USER':'reader','CALENDAR_SOURCE_PASSWORD':'a'*32,'CALENDAR_SOURCE_UPSTREAM':'https://example.com'}]:
        with pytest.raises(ValueError):module.settings(env)
    assert module.settings({'CALENDAR_SOURCE_USER':'reader','CALENDAR_SOURCE_PASSWORD':'a'*32})==('reader','a'*32)


def test_source_timezone_backend_is_checked_before_routes_are_loaded(monkeypatch):
    module=implementation()
    monkeypatch.delenv('PYTHONTZPATH',raising=False)
    with pytest.raises(ValueError,match='timezone'):module.timezone_profile()


def test_only_authenticated_get_routes_are_exposed():
    module=implementation()
    from fastapi.testclient import TestClient
    async def calendars():return {'schemaVersion':1}
    async def bundle(calendar_id:str,start:str,end:str):return {'calendarId':calendar_id,'start':start,'end':end}
    app=module.create_app(('reader','a'*32),calendars,bundle)
    with TestClient(app) as client:
        path='/api/v1/calendar/trading/v1/bundle'
        assert client.get(path).status_code==401
        assert client.get(path,auth=('reader','bad')).status_code==401
        assert client.get(path,auth=('bad','a'*32)).status_code==401
        params={'calendar_id':'exchange:XNYS','start':'2026-11-26','end':'2026-11-27'}
        response=client.get(path,params=params,auth=('reader','a'*32))
        assert response.status_code==200
        assert response.json()['calendarId']=='exchange:XNYS'
        assert client.post(path,json=params,auth=('reader','a'*32)).status_code==405
        assert client.get('/docs',auth=('reader','a'*32)).status_code==404
        assert client.get('/openapi.json',auth=('reader','a'*32)).status_code==404
        assert client.get('/health').status_code==200
        assert client.get(path,params={**params,'end':'2028-01-01'},auth=('reader','a'*32)).status_code==422
        assert client.get(path,params={**params,'upstream':'https://example.com'},auth=('reader','a'*32)).status_code==422
        assert 'a'*32 not in response.text
