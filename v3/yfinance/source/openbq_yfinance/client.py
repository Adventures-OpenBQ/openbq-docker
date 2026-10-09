# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Run the public synchronous yfinance API outside the server event loop."""
import asyncio
from collections.abc import Callable
from typing import Any
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError


def _disable_cookie_cache() -> None:
    """Avoid the SDK's pickle-backed persisted cookie cache.

    This process-wide SDK switch leaves cookies in memory only. Fail closed
    if a future SDK changes the cache contract rather than loading a pickle.
    """
    import yfinance.cache as cache
    cookie_cache = cache.get_cookie_cache()
    if not hasattr(cookie_cache, 'dummy'):
        raise OpenBBError('Unsupported Yahoo cookie cache; SDK compatibility review required.')
    cookie_cache.dummy = True


def _is_unauthorized(exc: Exception) -> bool:
    """Whether Yahoo refused the request as unauthorized (HTTP 401)."""
    response = getattr(exc, 'response', None)
    return getattr(response, 'status_code', None) == 401 or 'HTTP Error 401' in str(exc)


def _reset_session() -> None:
    """Replace the SDK's process-wide HTTP session, cookie and crumb.

    Yahoo expires a long-running process's session, and the SDK's own retry
    (the other cookie strategy) reuses the same cookie jar, so every call then
    fails with 401 until the process restarts. A fresh session is what a new
    process would have. Fail closed if the SDK's internals change.
    """
    from yfinance.data import YfData, new_session
    data = YfData()
    if not all(hasattr(data, name) for name in ('_cookie_lock', '_cookie', '_crumb', '_cookie_strategy')):
        raise OpenBBError('Unsupported Yahoo session layout; SDK compatibility review required.')
    data._set_session(new_session())
    with data._cookie_lock:
        data._cookie = None
        data._crumb = None
        data._cookie_strategy = 'basic'


async def call(operation: Callable[[], Any]) -> Any:
    """Run one SDK operation; retain an actionable upstream error and its cause.

    A 401 gets one retry on a fresh SDK session; any other failure is final.
    """
    try:
        _disable_cookie_cache()
        try:
            return await asyncio.to_thread(operation)
        except Exception as exc:
            if not _is_unauthorized(exc):
                raise
            await asyncio.to_thread(_reset_session)
            return await asyncio.to_thread(operation)
    except (OpenBBError, EmptyDataError):
        raise
    except Exception as exc:
        raise OpenBBError(f"Yahoo Finance request failed: {exc}") from exc


def ticker(symbol: str):
    """Construct a public yfinance Ticker without a shared mutable session."""
    import yfinance as yf
    return yf.Ticker(symbol)
