# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Bounded grid/chart projections of the existing decorated Polars pipeline."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from openbq_ta.registry import StudyError, col_suffix, get, resolve

from arts_charts.odp_bars import NotConfigured, Refused, check_interval
from arts_charts.ta.payload import ChartParams
from arts_charts.ta.warmup import pad_start, warmup_bars

MAX_REQUEST = 65536
MAX_RESPONSE = 2 * 1024 * 1024
MAX_CACHE = 256
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_INFLIGHT = 256
MAX_BARS = 10000
COMPUTE_TIMEOUT = 10
REQUEST_TIMEOUT = 5


class BoundedExecutor:
    """No waiting executor queue; permits survive cancellation until actual completion."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="shared-study")
        self.permits = threading.BoundedSemaphore(4)

    def submit(self, function, *args):
        if not self.permits.acquire(blocking=False):
            raise ValueError("STUDY_BUSY")
        try:
            future = self.pool.submit(function, *args)
        except BaseException:
            self.permits.release()
            raise
        future.add_done_callback(lambda done: self.permits.release())
        return future


_EXECUTOR = BoundedExecutor()
_SYMBOL = re.compile(r"[A-Za-z0-9.^_=-]{1,64}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=64)
    study: str = Field(min_length=1, max_length=64)
    output: str = Field(min_length=1, max_length=64)
    params: dict[str, int | float | str | bool | None] = Field(default_factory=dict, max_length=64)
    interval: str = Field(max_length=16)
    session: str
    basis: str
    provider: str = Field(max_length=32)
    points: int = Field(ge=1, le=256)
    definition_version: str | None = Field(default=None, max_length=128)


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    symbols: list[str] = Field(min_length=1, max_length=50)
    columns: list[Column] = Field(min_length=1, max_length=16)


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _project(frame, ind, req, params, context, version, meta, now):
    if get(ind.name).definition_version != version:
        raise ValueError("STUDY_DEFINITION_CHANGED")
    outputs = {}
    for output in ind.render:
        name = output + col_suffix(req)
        if name not in frame.columns:
            continue
        values = frame.tail(256)[name].to_list()
        dates = frame.tail(256)["date"].to_list()
        outputs[output] = [
            dict(
                time=_utc(stamp),
                value=None
                if value is None or isinstance(value, float) and not math.isfinite(value)
                else float(value),
            )
            for stamp, value in zip(dates, values)
            if stamp is not None
        ]
    payload = dict(
        study=ind.name,
        params=params,
        context=context,
        definition_version=version,
        outputs=outputs,
        input_cursor=meta.get("input_cursor"),
        coverage=meta.get("coverage"),
        as_of=_utc(now),
    )
    # Full input values identify forming/older revisions even if a selected study's
    # latest value happens to remain unchanged. No invented q cursor is attached.
    stamp = _json(
        dict(
            context=context,
            version=version,
            cursor=payload["input_cursor"],
            coverage=payload["coverage"],
        )
    )
    payload["revision"] = hashlib.sha256(frame.serialize() + stamp.encode()).hexdigest()
    size = len(_json(payload).encode())
    if size > MAX_RESPONSE:
        raise ValueError("STUDY_OUTPUT_LIMIT")
    payload["_cache_bytes"] = size
    return payload


class Results:
    def __init__(self, fetch, series_state, provider, *, clock=time.monotonic, now=None):
        self.fetch, self.series_state, self.provider = fetch, series_state, provider
        self.clock, self.now = clock, now or (lambda: datetime.now(timezone.utc))
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.inflight = {}
        self.slots = asyncio.Semaphore(4)

    def normalize(self, column):
        try:
            ind = get(column.study)
        except (KeyError, ValueError):
            return None, "STUDY_UNKNOWN"
        version = ind.definition_version
        if column.definition_version is not None and column.definition_version != version:
            return None, "STUDY_DEFINITION_CHANGED"
        if column.output not in ind.render:
            return None, "STUDY_OUTPUT_INVALID"
        if (
            column.session not in ("regular", "extended", "24hr")
            or column.basis not in ("adjusted", "raw")
            or column.provider not in ("", "yfinance", "eodhd", "temporaldb")
            or not re.fullmatch(r"[1-9][0-9]{0,4}[smhdwM]", column.interval)
        ):
            return None, "STUDY_CONTEXT_UNSUPPORTED"
        try:
            check_interval(column.interval, column.provider or self.provider)
        except Refused:
            return None, "STUDY_CONTEXT_UNSUPPORTED"
        # Cross-symbol/time/anchored studies retain their existing chart route.
        # This first scalar/series grid contract carries no anchor or peer source context.
        if ind.times or ind.tickers or ind.sessioned:
            return None, "STUDY_CONTEXT_UNSUPPORTED"
        try:
            req = resolve(ind.name, **column.params)
        except (StudyError, ValueError, TypeError):
            return None, "STUDY_PARAMS_INVALID"
        params = {k: v for k, v in req.params.items() if k != "style"}
        if any(abs(params[name]) > MAX_BARS for name in ind.windows):
            return None, "STUDY_LOOKBACK_LIMIT"
        count = (
            warmup_bars(
                [{"name": ind.name, "params": params}], lambda name: list(get(name).windows)
            )
            + 256
        )
        if count > MAX_BARS:
            return None, "STUDY_LOOKBACK_LIMIT"
        now = self.now()
        end = now.date().isoformat()
        try:
            start = pad_start(end, count, column.interval, None)
        except (OverflowError, ValueError):
            return None, "STUDY_LOOKBACK_LIMIT"
        context = dict(
            interval=column.interval,
            session=column.session,
            basis=column.basis,
            provider=column.provider or self.provider,
            input_start=start,
            input_end=end,
        )
        return (ind, req, params, context, version), None

    async def compute(self, symbol, normalized):
        ind, req, params, context, version = normalized
        async with self.slots:
            answer = await self.fetch(
                symbol,
                context["interval"],
                context["input_start"],
                context["input_end"],
                context["provider"],
                context["session"],
            )
            if len(answer[0]) > MAX_BARS:
                raise ValueError("STUDY_INPUT_LIMIT")
            cp = ChartParams(
                symbol=symbol,
                interval=context["interval"],
                provider=context["provider"],
                session=context["session"],
                basis=context["basis"],
            )
            _, frame, annotations, meta, error = await self.series_state(
                cp, None, answer, requests=[req], executor=_EXECUTOR
            )
            if error is not None:
                raise ValueError("STUDY_SOURCE_UNAVAILABLE")
            return await asyncio.wrap_future(
                _EXECUTOR.submit(
                    _project, frame, ind, req, params, context, version, meta, self.now()
                )
            )

    async def shared(self, symbol, normalized):
        ind, _, params, context, version = normalized
        key = _json([symbol, ind.name, params, context, version])
        cached = self.cache.get(key)
        if cached and self.clock() - cached[0] < 1:
            self.cache.move_to_end(key)
            return cached[1]
        task = self.inflight.get(key)
        if task is None:
            if len(self.inflight) >= MAX_INFLIGHT:
                raise ValueError("STUDY_BUSY")

            async def bounded():
                async with asyncio.timeout(COMPUTE_TIMEOUT):
                    return await self.compute(symbol, normalized)

            task = asyncio.create_task(bounded())
            self.inflight[key] = task

            def completed(done):
                self.inflight.pop(key, None)
                if done.cancelled() or done.exception() is not None:
                    return
                payload = done.result()
                size = payload.get("_cache_bytes", 0)
                previous = self.cache.pop(key, None)
                if previous:
                    self.cache_bytes -= previous[1].get("_cache_bytes", 0)
                self.cache[key] = (self.clock(), payload)
                self.cache_bytes += size
                self.cache.move_to_end(key)
                while len(self.cache) > MAX_CACHE or self.cache_bytes > MAX_CACHE_BYTES:
                    _, (_, evicted) = self.cache.popitem(last=False)
                    self.cache_bytes -= evicted.get("_cache_bytes", 0)

            task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def one(self, symbol, column):
        base = dict(
            id=column.id,
            symbol=symbol,
            study=column.study,
            output=column.output,
            params=column.params,
            context=dict(
                interval=column.interval,
                session=column.session,
                basis=column.basis,
                provider=column.provider or self.provider,
            ),
            definition_version=column.definition_version,
            latest=None,
            points=[],
            status="error",
            revision=None,
            as_of=_utc(self.now()),
            input_cursor=None,
            coverage=None,
        )
        try:
            normalized, error = self.normalize(column)
        except (ValueError, OverflowError, TypeError):
            return {**base, "error_code": "STUDY_PARAMS_INVALID"}
        if error:
            return {**base, "error_code": error}
        try:
            calculated = await self.shared(symbol, normalized)
            points = calculated["outputs"].get(column.output)
            if points is None:
                return {**base, "error_code": "STUDY_OUTPUT_UNAVAILABLE"}
            latest = points[-1]["value"] if points else None
            return {
                **base,
                **{k: v for k, v in calculated.items() if k not in ("outputs", "_cache_bytes")},
                "latest": latest,
                "points": points[-column.points :],
                "status": "warming_up" if latest is None else "ok",
            }
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                code = "STUDY_TIMEOUT"
            elif isinstance(exc, (NotConfigured, Refused)):
                code = "STUDY_CONTEXT_UNSUPPORTED"
            else:
                code = (
                    str(exc)
                    if str(exc)
                    in (
                        "STUDY_BUSY",
                        "STUDY_INPUT_LIMIT",
                        "STUDY_DEFINITION_CHANGED",
                        "STUDY_OUTPUT_LIMIT",
                    )
                    else "STUDY_SOURCE_UNAVAILABLE"
                )
            return {**base, "error_code": code}


def study_router(fetch, series_state, provider):
    api = APIRouter()
    results = Results(fetch, series_state, provider)

    @api.get("/study_catalog")
    async def study_catalog():
        from openbq_ta.registry import catalog

        return dict(
            schema_version=1,
            studies=[{**entry, "outputs": list(entry["render"])} for entry in catalog()],
        )

    @api.post("/study_results")
    async def study_results(request: Request):
        body = bytearray()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_REQUEST:
                        raise HTTPException(413, "STUDY_REQUEST_LIMIT")
                    body.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "STUDY_REQUEST_TIMEOUT") from None
        try:
            batch = Batch.model_validate_json(body)
            if (
                batch.schema_version != 1
                or len({symbol.upper() for symbol in batch.symbols}) != len(batch.symbols)
                or any(not _SYMBOL.fullmatch(s) for s in batch.symbols)
                or any(not _ID.fullmatch(c.id) for c in batch.columns)
                or len({c.id for c in batch.columns}) != len(batch.columns)
            ):
                raise ValueError()
        except (ValidationError, ValueError):
            raise HTTPException(422, "STUDY_REQUEST_INVALID") from None
        values = await asyncio.gather(
            *(
                results.one(symbol.upper(), column)
                for symbol in batch.symbols
                for column in batch.columns
            )
        )
        payload = dict(schema_version=1, results=values)
        encoded = _json(payload)
        if len(encoded.encode()) > MAX_RESPONSE:
            raise HTTPException(413, "STUDY_RESPONSE_LIMIT")
        return JSONResponse(payload)

    return api
