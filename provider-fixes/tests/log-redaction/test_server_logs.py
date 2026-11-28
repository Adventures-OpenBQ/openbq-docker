# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Complete Uvicorn-style exception formatting must not restore secret text."""
import asyncio
import io
import logging
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from openbb_core.api.app_loader import AppLoader

class ServerLogRedaction(unittest.TestCase):
    def test_generic_exception_response_and_chained_server_log_are_safe(self):
        marker='synthetic-private-unit-marker'
        stream=io.StringIO();handler=logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger=logging.getLogger('uvicorn.error');logger.addHandler(handler)
        try:
            with patch.dict('os.environ', {'FRED_API_KEY':marker}):
                app=FastAPI();AppLoader.add_exception_handlers(app)
                @app.get('/unexpected')
                async def unexpected():
                    try:raise ValueError('inner '+marker)
                    except ValueError as cause:
                        raise RuntimeError('https://unit.invalid/data?api_key='+marker) from cause
                async def call():
                    transport=httpx.ASGITransport(app,raise_app_exceptions=True)
                    async with httpx.AsyncClient(transport=transport,base_url='http://unit.invalid') as c:
                        try:await c.get('/unexpected')
                        except Exception:
                            # Uvicorn logs the original error after ServerErrorMiddleware re-raises it.
                            logger.error('Exception in ASGI application',exc_info=True)
                    transport=httpx.ASGITransport(app,raise_app_exceptions=False)
                    async with httpx.AsyncClient(transport=transport,base_url='http://unit.invalid') as c:
                        return await c.get('/unexpected')
                response=asyncio.run(call())
                self.assertEqual(response.status_code,500)
                self.assertNotIn(marker,response.text)
                self.assertIn('RuntimeError',stream.getvalue())
                self.assertIn('ValueError',stream.getvalue())
                self.assertNotIn(marker,stream.getvalue())
        finally:logger.removeHandler(handler)

    def test_access_formatter_keeps_tuple_shape_and_redacts_url(self):
        from uvicorn.logging import AccessFormatter
        marker='synthetic-private-unit-marker'
        stream=io.StringIO();handler=logging.StreamHandler(stream)
        handler.setFormatter(AccessFormatter('%(request_line)s %(status_code)s',use_colors=False))
        logger=logging.getLogger('uvicorn.access');old_level=logger.level;logger.setLevel(logging.INFO);logger.addHandler(handler)
        try:
            with patch.dict('os.environ', {'FRED_API_KEY':marker}):
                AppLoader.add_exception_handlers(FastAPI())
                logger.info('%s - "%s %s HTTP/%s" %d', 'unit','GET','/api?token='+marker,'1.1',200)
                self.assertIn('GET /api?',stream.getvalue())
                self.assertIn('200',stream.getvalue())
                self.assertNotIn(marker,stream.getvalue())
        finally:
            logger.removeHandler(handler);logger.setLevel(old_level)

    def test_real_uvicorn_logging_configuration_is_safe_after_startup(self):
        import copy
        import threading
        import time
        import uvicorn
        marker='synthetic-server-private-marker'
        stream=io.StringIO()
        with patch.dict('os.environ', {'FRED_API_KEY':marker}):
            app=FastAPI();AppLoader.add_exception_handlers(app)
            @app.get('/unexpected')
            async def unexpected():
                try:raise ValueError('inner '+marker)
                except ValueError as cause:raise RuntimeError('https://unit.invalid?api_key='+marker) from cause
            config=copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
            config['handlers']['default']['stream']=stream
            config['handlers']['access']['stream']=stream
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,log_config=config))
            thread=threading.Thread(target=server.run,daemon=True);thread.start()
            try:
                deadline=time.monotonic()+10
                while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(server.started)
                port=server.servers[0].sockets[0].getsockname()[1]
                response=httpx.get(f'http://127.0.0.1:{port}/unexpected?token='+marker,trust_env=False)
                self.assertEqual(response.status_code,500)
                self.assertNotIn(marker,response.text)
            finally:
                server.should_exit=True;thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertIn('RuntimeError',stream.getvalue())
            self.assertIn('ValueError',stream.getvalue())
            self.assertNotIn(marker,stream.getvalue())
