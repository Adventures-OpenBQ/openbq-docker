# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Extend the real OpenBQ reference application with the Episode 3 fixtures."""
import os
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from main import app
from core import WIDGETS, ROOT_PATH
from server import DATA, WIDGETS as DEMO_WIDGETS

ROOT = ROOT_PATH

def install_demo(application, registry):
    collisions = registry.keys() & DEMO_WIDGETS.keys()
    if collisions:
        raise ValueError('Episode 3 widget IDs collide with the reference registry')
    router = APIRouter()
    @router.get('/health')
    def health():
        return {'status': 'ok'}
    @router.get('/agents.json')
    def agents():
        return {}
    @router.get('/assets/bdobb-logo.svg')
    def logo():
        return FileResponse(ROOT / 'assets/bdobb-logo.svg', media_type='image/svg+xml')
    @router.get('/bundle.apps.json')
    def bundle():
        return FileResponse(ROOT / 'bundle.apps.json', media_type='application/json')
    @router.get('/market-examples.apps.json')
    def market_examples():
        return FileResponse(ROOT / 'market-examples.apps.json', media_type='application/json')
    @router.get('/data/prices')
    def prices():
        return DATA['prices']
    @router.get('/data/nulls')
    def nulls():
        return DATA['nulls']
    registry.update(DEMO_WIDGETS)
    application.include_router(router)

install_demo(app, WIDGETS)

# Omni routes that run the caller's code on this server, by language: SQL runs
# the request's query against an in-memory sqlite of mock data; Python runs the
# request's code with exec(). OPENBQ_OMNI_EXEC_ALLOWED lists the languages this
# backend may execute (e.g. "sql" or "sql,python"); unset, nothing executes.
# Display-only Omni widgets are not gated.
CODE_EXECUTING_OMNI = {'/omni-sql-widget': 'sql', '/omni-python-widget': 'python'}

def allowed_languages():
    value = os.environ.get('OPENBQ_OMNI_EXEC_ALLOWED', '')
    return {lang.strip().lower() for lang in value.split(',') if lang.strip()}

async def refuse_omni_code_runs(request, call_next):
    language = next((lang for path, lang in CODE_EXECUTING_OMNI.items() if request.url.path.endswith(path)), None)
    if language and language not in allowed_languages():
        return JSONResponse(
            {'detail': f"Omni code execution in '{language}' is not allowed on this backend (OPENBQ_OMNI_EXEC_ALLOWED)."},
            status_code=403,
        )
    return await call_next(request)

# Innermost, so the refusal still passes through CORS and browsers can read it.
app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=refuse_omni_code_runs))
