"""Extend the real OpenBQ reference application with the Episode 3 fixtures."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
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
