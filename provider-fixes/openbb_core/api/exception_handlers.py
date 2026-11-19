# Derived from the OpenBB Platform (https://github.com/OpenBB-finance/OpenBB),
# Copyright (c) 2021-2026 OpenBB Inc., licensed under the Apache License, Version 2.0.
# Modifications Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Exception handlers module."""

import json
import logging
import os
import traceback
import re
from collections.abc import Iterable
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.env import Env
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError

logger = logging.getLogger("uvicorn.error")

# Providers put keys in the URL (FRED api_key, EconDB token, ...); aiohttp errors quote the URL.
_SECRET = re.compile(r"(?i)((?:api_?key|apikey|token|registrationkey)=)[^&\s'\"\\]+")


def _redact(text: str) -> str:
    text = _SECRET.sub(r"\1***", text)
    # Tracebacks may mention a credential without its query parameter name.
    values = {value for name, value in os.environ.items()
              if value and len(value) >= 4 and re.search(
                  r"(?:API_?KEY|APP_TOKEN|TOKEN|PASSWORD|SECRET|SECRET_ACCESS_KEY)$", name)}
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def _redact_log_value(value):
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_log_value(item) for key, item in value.items()}
    return value


class _SecretLogFilter(logging.Filter):
    """Sanitize complete server records, including chained exception formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_log_value(record.msg)
        # Preserve the structured tuple expected by Uvicorn's AccessFormatter.
        record.args = _redact_log_value(record.args)
        if record.exc_info:
            record.exc_text = _redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = _redact(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact(record.stack_info)
        return True


def install_log_redaction() -> None:
    """Install after Uvicorn config as well as at app construction."""
    for name in ("uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        if not any(isinstance(item, _SecretLogFilter) for item in target.filters):
            target.addFilter(_SecretLogFilter())


def _is_query_model(title: str) -> bool:
    """Whether a validation error's model is a QueryParams class (client input), not a Data model."""
    from openbb_core.provider.abstract.query_params import QueryParams

    classes = [QueryParams]
    while classes:
        cls = classes.pop()
        if cls.__name__ == title:
            return True
        classes.extend(cls.__subclasses__())
    return False


class ExceptionHandlers:
    """Exception handlers."""

    @staticmethod
    async def _handle(exception: Exception, status_code: int, detail: Any):
        """Exception handler."""
        if Env().DEBUG_MODE:
            raise exception
        logger.error(_redact(str(exception)))
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": json.loads(_redact(json.dumps(jsonable_encoder(detail)))),
            },
        )

    @staticmethod
    async def exception(_: Request, error: Exception) -> JSONResponse:
        """Exception handler for Base Exception."""
        if isinstance(error, TimeoutError):
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=504,
                detail=str(error)
                or "The upstream data source did not respond in time.",
            )
        if isinstance(error, json.JSONDecodeError):
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=502,
                detail="The data source returned a response that is not valid JSON.",
            )
        errors = error.errors if hasattr(error, "errors") else error
        if callable(errors):
            errors = errors()

        if errors:
            if isinstance(errors, ValueError):
                return await ExceptionHandlers._handle(
                    exception=errors,
                    status_code=422,
                    detail=errors.args,
                )
            # Required parameters are missing and is not handled by ValidationError.
            title = getattr(error, "title", "")
            if isinstance(errors, Iterable) and (
                "QueryParams" in title or _is_query_model(title)
            ):
                for err in errors:
                    if err.get("type") == "missing":
                        return await ExceptionHandlers._handle(
                            exception=error,
                            status_code=422,
                            detail=jsonable_encoder(err),
                        )
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=500,
            detail=f"Unexpected Error -> {error.__class__.__name__} -> {error}",
        )

    @staticmethod
    async def validation(
        request: Request, error: ValidationError | ResponseValidationError
    ):
        """Exception handler for ValidationError."""
        # Some validation is performed at Fetcher level.
        # So we check if the validation error comes from a QueryParams class.
        # And that it is in the request query params.
        # If yes, we update the error location with query.
        # If not, we handle it as a base Exception error.
        query_params = dict(request.query_params)
        if isinstance(error, ResponseValidationError):
            detail = [
                {
                    **{k: v for k, v in err.items() if k != "ctx"},
                    "loc": ("query",) + err.get("loc", ()),
                }
                for err in error.errors()
            ]
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=422,
                detail=detail,
            )
        try:
            errors = (
                error.errors(include_url=False)
                if hasattr(error, "errors")
                else error.errors
            )
        except Exception:
            errors = error.errors if hasattr(error, "errors") else error
        all_in_query = all(
            loc in query_params
            for err in errors  # ty: ignore[not-iterable]
            for loc in err.get("loc", ())
        )
        if ("QueryParams" in error.title or _is_query_model(error.title)) and all_in_query:
            detail = [
                {
                    **{k: v for k, v in err.items() if k != "ctx"},
                    "loc": ("query",) + err.get("loc", ()),
                }
                for err in errors  # ty: ignore[not-iterable]
            ]
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=422,
                detail=detail,
            )
        return await ExceptionHandlers.exception(request, error)

    @staticmethod
    async def openbb(_: Request, error: OpenBBError):
        """Exception handler for OpenBBError."""
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=400,
            detail=str(error.original),
        )

    @staticmethod
    async def empty_data(_: Request, error: EmptyDataError):
        """Exception handler for EmptyDataError."""
        return Response(status_code=204)

    @staticmethod
    async def unauthorized(_: Request, error: UnauthorizedError):
        """Exception handler for OpenBBError."""
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=502,
            detail=str(error.original),
        )
