# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Read-only bounded bridge to the one configured shared study service."""

import asyncio
import json
import os

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from .auth import auth_enabled, credentials_ok

REQUEST_BYTES = 64 * 1024
RESPONSE_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 5


def _json(body):
    def invalid(_):
        raise ValueError("non-finite JSON")

    return json.loads(body, parse_constant=invalid)


class StudyProxy:
    def __init__(self, *, transport=None):
        self.transport = transport
        self.origin = None
        self.active = 0
        raw = os.getenv("LIVE_GRID_STUDY_ORIGIN", "").strip()
        try:
            url = httpx.URL(raw)
            if (
                url.scheme in ("http", "https")
                and url.host
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and url.path in ("", "/")
            ):
                self.origin = str(url).rstrip("/")
        except (httpx.InvalidURL, ValueError):
            pass

    @property
    def configured(self):
        return bool(
            self.origin
            and auth_enabled()
            and os.getenv("OPENBB_API_USERNAME")
            and os.getenv("OPENBB_API_PASSWORD")
        )

    async def exchange(self, request: Request):
        if not self.configured:
            return JSONResponse({"detail": "study service is not configured"}, status_code=503)
        if not credentials_ok(request.headers.get("authorization")):
            return JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Basic"},
            )
        if request.url.query:
            return JSONResponse({"detail": "query parameters are not supported"}, status_code=400)
        if self.active >= 8:
            return JSONResponse({"detail": "study service is busy"}, status_code=429)
        self.active += 1
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                return await self._admitted(request)
        except TimeoutError:
            return JSONResponse({"detail": "study service timed out"}, status_code=504)
        finally:
            self.active -= 1

    async def _admitted(self, request):
        body = None
        if request.method == "POST":
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                return JSONResponse({"detail": "JSON required"}, status_code=415)
            try:
                length = int(request.headers.get("content-length", "0"))
                if length < 0:
                    raise ValueError()
            except ValueError:
                return JSONResponse({"detail": "invalid content length"}, status_code=400)
            if length > REQUEST_BYTES:
                return JSONResponse({"detail": "request too large"}, status_code=413)
            chunks = []
            total = 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > REQUEST_BYTES:
                    return JSONResponse({"detail": "request too large"}, status_code=413)
                chunks.append(chunk)
            body = b"".join(chunks)
            try:
                _json(body)
            except (ValueError, UnicodeError):
                return JSONResponse({"detail": "invalid JSON"}, status_code=400)
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=TIMEOUT_SECONDS,
                    follow_redirects=False,
                    trust_env=False,
                    auth=httpx.BasicAuth(
                        os.environ["OPENBB_API_USERNAME"], os.environ["OPENBB_API_PASSWORD"]
                    ),
                ) as client:
                    async with client.stream(
                        request.method,
                        self.origin + request.url.path,
                        content=body,
                        headers={"accept": "application/json", "content-type": "application/json"},
                    ) as response:
                        # Provider/credential details from error documents never cross the bridge.
                        if response.status_code != 200:
                            status = (
                                response.status_code
                                if response.status_code in (400, 422, 429, 503)
                                else 502
                            )
                            return JSONResponse(
                                {"detail": "study service rejected request"}, status_code=status
                            )
                        if int(response.headers.get("content-length", "0")) > RESPONSE_BYTES:
                            raise ValueError("response too large")
                        parts = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > RESPONSE_BYTES:
                                raise ValueError("response too large")
                            parts.append(chunk)
                        value = _json(b"".join(parts))
                        if (
                            not isinstance(value, dict)
                            or type(value.get("schema_version")) is not int
                            or value.get("schema_version") != 1
                        ):
                            raise ValueError("invalid response envelope")
                        return JSONResponse(value)
        except (httpx.TimeoutException, TimeoutError):
            return JSONResponse({"detail": "study service timed out"}, status_code=504)
        except (httpx.HTTPError, ValueError, UnicodeError):
            return JSONResponse({"detail": "study service unavailable"}, status_code=502)


def attach_study_proxy(app, *, transport=None):
    proxy = StudyProxy(transport=transport)
    app.state.study_proxy = proxy
    app.get("/study_catalog")(proxy.exchange)
    app.post("/study_results")(proxy.exchange)
    return proxy
