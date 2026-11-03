"""OpenBQ operational settings; imports never connect to PostgreSQL."""
import asyncio
from contextlib import asynccontextmanager
import os
from starlette.responses import JSONResponse, Response
from .config import Config, SettingsUnavailable, backend
from .store import Store

_runtime = None


class Runtime:
    def __init__(self, store):
        self.store = store
        self.slots = asyncio.Semaphore(2)
        self.pending = 0

    async def run(self, fn, *args):
        if self.pending >= 10:
            raise SettingsUnavailable()
        self.pending += 1
        acquired = False
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=10)
            acquired = True
            # Shield transaction completion: cancelled HTTP requests cannot release
            # the slot early while their blocking transaction still owns a connection.
            task = asyncio.create_task(asyncio.to_thread(fn, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        finally:
            if acquired:
                self.slots.release()
            self.pending -= 1


@asynccontextmanager
async def lifespan(app, previous):
    global _runtime
    if backend() != "postgresql":
        async with previous(app):
            yield
        return
    store = Store(Config.read())
    try:
        await asyncio.to_thread(store.verify)
        _runtime = Runtime(store)
        async with previous(app):
            yield
    except Exception:
        raise SettingsUnavailable() from None
    finally:
        _runtime = None
        await asyncio.to_thread(store.close)


async def dispatch(request, key_module=None):
    from .private_state import PREFIX, handle
    try:
        if backend() != "postgresql":
            return Response(status_code=404)
        if _runtime is None or _runtime.store.pid != os.getpid():
            raise SettingsUnavailable()
        if request.url.path.startswith(PREFIX):
            return await handle(request, _runtime)
        if key_module._credential(request) is None:
            return JSONResponse({"detail": "Invalid or missing credentials."}, 401,
                                {"WWW-Authenticate": "Basic"})
        # Bound reception before the worker; the cached body has no ASGI I/O in it.
        limit = key_module.MAX_BYTES if request.url.path == "/pro/display-settings" else key_module.MAX_SYNC_BYTES
        chunks = []; size = 0
        async for part in request.stream():
            size += len(part)
            if size > limit:
                return JSONResponse({"detail": "Settings exceed 1 MB." if limit == key_module.MAX_BYTES else "The body exceeds 5 MB."}, 413)
            chunks.append(part)
        request._body = b"".join(chunks)
        def operation():
            with _runtime.store.transaction("key", _runtime.store.config.principal) as documents:
                token = key_module.DOCUMENTS.set(documents)
                try:
                    return asyncio.run(key_module._settings(request))
                finally:
                    key_module.DOCUMENTS.reset(token)
        return await _runtime.run(operation)
    except Exception:
        return JSONResponse({"detail": "Settings unavailable."}, 503)
