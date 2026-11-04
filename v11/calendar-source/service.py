# SPDX-License-Identifier: Apache-2.0
"""Read-only, authenticated wrapper over the source-controlled calendar route."""
from datetime import date
import re
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import secrets
import zoneinfo

from fastapi import FastAPI, Request
from fastapi.security import HTTPBasic
from starlette.responses import JSONResponse


def settings(env):
    allowed={'CALENDAR_SOURCE_USER','CALENDAR_SOURCE_PASSWORD'}
    if any(key.startswith('CALENDAR_SOURCE_') and key not in allowed for key in env):
        raise ValueError('unsupported calendar source configuration')
    user,password=(env.get(key,'') for key in ('CALENDAR_SOURCE_USER','CALENDAR_SOURCE_PASSWORD'))
    if not (1<=len(user)<=128 and 32<=len(password)<=256 and ':' not in user and
            all(32<ord(char)<127 for char in user+password)):
        raise ValueError('calendar source requires bounded private Basic credentials')
    return user,password


def timezone_profile():
    # ZoneInfo must use the pinned wheel, never the container distribution's tzfiles.
    if os.environ.get('PYTHONTZPATH')!='' or zoneinfo.TZPATH:
        raise ValueError('timezone backend must be pinned tzdata with empty PYTHONTZPATH')
    expected={'tzdata':'2026.5','exchange_calendars':'4.13.2','pydantic':'2.13.5'}
    if any(importlib.metadata.version(name)!=version for name,version in expected.items()):
        raise ValueError('unqualified calendar source package profile')
    return expected


def create_app(credentials,calendars,bundle):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    basic=HTTPBasic(auto_error=False)

    @app.middleware('http')
    async def authenticate(request:Request,call_next):
        if request.url.path!='/health':
            try:value=await basic(request)
            except Exception:value=None
            good=False
            if value is not None:
                good=secrets.compare_digest(value.username,credentials[0]) & secrets.compare_digest(value.password,credentials[1])
            if not good:
                return JSONResponse({'error':{'code':'unauthorized'}},status_code=401,headers={'WWW-Authenticate':'Basic'})
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/health')
    async def health():return {'status':'ok'}

    app.get('/api/v1/calendar/trading/v1/calendars')(calendars)
    @app.get('/api/v1/calendar/trading/v1/bundle')
    async def bounded_bundle(request:Request,calendar_id:str,start:str,end:str):
        try:
            first,last=date.fromisoformat(start),date.fromisoformat(end)
            if (set(request.query_params)!={'calendar_id','start','end'} or
                any(len(request.query_params.getlist(key))!=1 for key in request.query_params) or
                not re.fullmatch(r'exchange:[A-Z0-9_]{1,32}',calendar_id) or
                first.isoformat()!=start or last.isoformat()!=end or not 0<=(last-first).days<366):
                raise ValueError('invalid bounded request')
        except ValueError:
            return JSONResponse({'error':{'code':'invalid_calendar_request'}},status_code=422)
        response=await bundle(calendar_id,start,end)
        if hasattr(response,'body') and len(response.body)>1048576:
            return JSONResponse({'error':{'code':'resource_limit'}},status_code=413)
        return response
    return app


def application():
    credentials=settings(os.environ)
    timezone_profile()
    # Fixed build-time source, no configured import path or arbitrary upstream.
    path=Path(__file__).with_name('calendar_v1.py')
    spec=importlib.util.spec_from_file_location('qualified_calendar_route',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return create_app(credentials,module.capabilities,module.bundle)
