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

# Omni routes that run the caller's code on this server. The Python route is
# already stripped at build (patch-omni-python.py); SQL runs the request's query
# against an in-memory sqlite of mock data. Display-only Omni widgets are not
# gated. OPENBQ_OMNI_EXEC_ALLOWED=true lets this backend execute; unset, refused.
CODE_EXECUTING_OMNI = ('/omni-sql-widget',)

async def refuse_omni_code_runs(request, call_next):
    allowed = os.environ.get('OPENBQ_OMNI_EXEC_ALLOWED', '').strip().lower() in ('1', 'true', 'yes')
    if not allowed and request.url.path.endswith(CODE_EXECUTING_OMNI):
        return JSONResponse(
            {'detail': 'Omni code execution is not allowed on this backend (OPENBQ_OMNI_EXEC_ALLOWED).'},
            status_code=403,
        )
    return await call_next(request)

# Innermost, so the refusal still passes through CORS and browsers can read it.
app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=refuse_omni_code_runs))
