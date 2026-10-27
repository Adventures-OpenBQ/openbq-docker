# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Daily bars from TemporalDB Gold, for a chart whose provider is `temporaldb`.

TemporalDB's HTTP API (0.5.0, the image openbq-docker v11 pins), with a bearer token
from TemporalDB's scope policy -- the backend has no per-capability scopes; those are
its MCP adapter's:

1. Once per process, `POST /temporal/v1/queries/save {key, definition}` saves this
   server's one dataset query. The save is durably idempotent per principal and key,
   and the key carries the definition's digest: every arts-charts instance with the
   same token gets the same query and revision back, and a changed definition is a new
   query, never a conflict. Executions name that revision explicitly. A retired query
   is refused (403) while its key still answers with it, so on that refusal the query is
   saved again under the key's next generation (`/g2`, `/g3`, ...) and the read goes on,
   once per read and logged once; instances converge on the same generation.
2. A read starts `POST /temporal/v1/executions` with the symbol and window in the
   current Gold (`current_corrected`, no manifest: TemporalDB pins the dataset's Gold
   head, or refuses 409 when there is none -- never Silver), polls
   `GET /temporal/v1/executions/{id}` and pages `GET .../pages?cursor=` until
   `next_cursor` is null. The whole read has LIMIT_S; past it the execution is
   cancelled.

`1w` and `1M` are resampled here from the same daily rows (the bar-widths ruling allows a
dividing source), stamped as EODHD stamps its own (sampled 2026-10-23): a week runs
Monday to Sunday and a month is the calendar month, each stamped with its first trading
day in the window -- 2026-09-08 for the week of Labor Day, 2026-08-03 for August 2026.
yfinance stamps the calendar Monday and the 1st instead, so a chart switched between
temporaldb and yfinance moves those bars by a day or two; EODHD's do not move.

Anything short of every page of a complete result -- a refusal, a failed or cancelled
execution, a truncated page, the time limit -- raises TemporalUnavailable: bars
unavailable, never part of a history. ComposedBars paces every question (one answer a
bar, at most 15 minutes, with its failure backoff), as for the ODP sources.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import date
from hashlib import sha256
from itertools import groupby

import httpx

from arts_charts.classify import snapshot_ticker
from arts_charts.odp_bars import UNKNOWN_META

log = logging.getLogger("arts-charts.temporaldb")

#: What a temporaldb chart may ask for: Gold's daily bars, and weeks and months built from them.
INTERVALS = ("1d", "1w", "1M")
DAILY_ONLY = "TemporalDB serves daily history; choose yfinance or eodhd for intraday"
DEFAULT_DATASET = "eodhd.eod"
#: The overall cap on one read: save (first time), start, polls and every page.
LIMIT_S = 15.0
#: TemporalDB's largest page (ExecutionService.start allows 1..10000).
PAGE_SIZE = 10_000
POLL_S, MAX_POLL_S = 0.1, 1.0

#: The Gold daily datasets this server reads: (the capture's request symbol for a chart
#: symbol, the identity fields an execution binds).
DATASETS = {
    # EODHD's ticker, as openbq-eodhd qualifies a bare symbol before calling EODHD (AAPL ->
    # AAPL.US, BTC-USD -> BTC-USD.CC, EURUSD -> EURUSD.FOREX); the eod identity selects
    # dates itself (runner._filter: from/to).
    "eodhd.eod": (snapshot_ticker, ("symbol", "from", "to")),
    # The symbol as OdpBars sends the yfinance equity route (every asset class); Yahoo's
    # identity has no date selector, so the window is cut here.
    "yfinance.YfinanceEquityHistorical": (str, ("symbol",)),
}
#: The identity values the saved definition carries; each execution binds its own.
PLACEHOLDERS = {"symbol": "SPY", "from": "1970-01-01", "to": "2099-12-31"}


class TemporalUnavailable(RuntimeError):
    """A TemporalDB read that did not complete: bars unavailable (a 502, the worker's retry)."""


def query_definition(dataset: str) -> dict:
    ticker, fields = DATASETS[dataset]
    placeholders = {**PLACEHOLDERS, "symbol": ticker(PLACEHOLDERS["symbol"])}
    return {
        # control.query_create assigns the real query_id and revision 1.
        "query_id": "00000000-0000-0000-0000-000000000000", "revision": 1,
        "title": f"arts-charts daily bars ({dataset})",
        "description": "One symbol's Gold daily bars over a window. Saved by arts-charts.",
        "kind": "dataset",
        "parameters": [{"name": f, "type": "string" if f == "symbol" else "date"}
                       for f in fields],
        "request": {"dataset_id": dataset, "parameters": {f: placeholders[f] for f in fields}},
        "temporal": {"mode": "current_corrected"},
        "schema_expectation": [],
    }


def query_key(definition: dict, generation: int = 1) -> str:
    digest = sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:16]
    return f"arts-charts/{definition['request']['dataset_id']}/{digest}/g{generation}"


def to_bar(row: dict) -> dict:
    """A Gold daily_price row (arrow-json-v1: decimal strings) as a history bar. An
    auto-adjusted Yahoo row has adjusted prices only; a row with neither fails the read."""
    def price(name: str) -> float:
        raw = row.get("raw_" + name)
        return float(row["adjusted_" + name] if raw is None else raw)
    adjusted = row.get("adjusted_close")
    return {"date": str(row["effective_from"])[:10], "open": price("open"),
            "high": price("high"), "low": price("low"), "close": price("close"),
            "volume": float(row.get("volume") or 0),
            "adjusted_close": None if adjusted is None else float(adjusted)}


def resample(bars: list[dict], interval: str) -> list[dict]:
    """Daily bars (oldest first) as `1w` (ISO week) or `1M` (calendar month) bars, each
    stamped with its first day; `1d` unchanged. The period's adjusted close is its last
    day's (None when that day has none: a live bar, whose close then stands in)."""
    if interval == "1d":
        return bars
    def period(bar):
        day = date.fromisoformat(bar["date"])
        return day.isocalendar()[:2] if interval == "1w" else (day.year, day.month)
    out = []
    for _, group in groupby(bars, key=period):
        days = list(group)
        out.append({"date": days[0]["date"], "open": days[0]["open"],
                    "high": max(d["high"] for d in days), "low": min(d["low"] for d in days),
                    "close": days[-1]["close"], "volume": sum(d["volume"] for d in days),
                    "adjusted_close": days[-1].get("adjusted_close")})
    return out


def _json(response: httpx.Response) -> dict:
    if response.is_error:
        try:
            code = response.json()["error"]["code"]
        except Exception:  # noqa: BLE001 - a body that is not TemporalDB's envelope
            code = "unknown"
        raise TemporalUnavailable(f"TemporalDB HTTP {response.status_code} {code}")
    return response.json()


class TemporalGoldBars:
    """`await bars(symbol, interval, start, end) -> (bars, meta)` from one Gold dataset."""

    def __init__(self, base_url: str, token: str, dataset: str = DEFAULT_DATASET,
                 transport: httpx.AsyncBaseTransport | None = None, limit: float = LIMIT_S):
        if dataset not in DATASETS:
            raise ValueError(f"ARTS_CHARTS_TEMPORAL_DATASET must be one of "
                             f"{', '.join(DATASETS)}, not {dataset!r}")
        self._base, self._dataset, self._limit = base_url.rstrip("/"), dataset, limit
        self._headers = {"Authorization": f"Bearer {token}"}
        self._transport = transport
        self._query: tuple[str, int] | None = None
        self._generation = 1
        self._lock = asyncio.Lock()

    async def __call__(self, symbol: str, interval: str, start: str, end: str):
        if interval not in INTERVALS:  # ComposedBars.check refuses these first, as a 422
            raise ValueError(DAILY_ONLY)
        ticker, fields = DATASETS[self._dataset]
        wanted = {"symbol": ticker(symbol), "from": start[:10], "to": end[:10]}
        started: list[str] = []
        async with httpx.AsyncClient(base_url=self._base, headers=self._headers,
                                     timeout=self._limit, transport=self._transport) as client:
            try:
                async with asyncio.timeout(self._limit):
                    rows = await self._read(client, {f: wanted[f] for f in fields}, started)
            except TimeoutError:
                if started:  # best effort: TemporalDB's own deadline ends it otherwise
                    with contextlib.suppress(httpx.HTTPError):
                        await client.delete(f"/temporal/v1/executions/{started[0]}",
                                            timeout=2.0)
                raise TemporalUnavailable(
                    f"TemporalDB execution not complete within {self._limit:g} s") from None
            except httpx.HTTPError as exc:  # its text can carry the URL: the class only
                raise TemporalUnavailable(f"TemporalDB {type(exc).__name__}") from None
        bars = sorted((to_bar(r) for r in rows), key=lambda b: b["date"])
        bars = [b for b in bars if start[:10] <= b["date"] <= end[:10]]
        return resample(bars, interval), {**UNKNOWN_META, "cache": "temporaldb"}

    async def _saved(self, client: httpx.AsyncClient) -> tuple[str, int]:
        async with self._lock:
            if self._query is None:
                definition = query_definition(self._dataset)
                saved = _json(await client.post("/temporal/v1/queries/save", json={
                    "key": query_key(definition, self._generation), "definition": definition}))
                self._query = (saved["query_id"], saved["revision"])
            return self._query

    async def _renew(self, refused: str) -> None:
        """Forget a query TemporalDB refused, unless another read already replaced it."""
        async with self._lock:
            if self._query is not None and self._query[0] == refused:
                self._query = None
                self._generation += 1
                log.warning("TemporalDB refused arts-charts' saved query; saving it again "
                            "(generation %d)", self._generation)

    async def _read(self, client: httpx.AsyncClient, params: dict, started: list[str]):
        for attempt in (1, 2):
            query_id, revision = await self._saved(client)
            response = await client.post("/temporal/v1/executions", json={
                "query_id": query_id, "revision": revision, "params": params,
                "context": {"mode": "current_corrected"}, "page_size": PAGE_SIZE})
            if response.status_code != 403 or attempt == 2:
                break
            await self._renew(query_id)  # retired: the next generation, once per read
        execution = _json(response)["execution_id"]
        started.append(execution)
        delay = POLL_S
        while (state := _json(await client.get(f"/temporal/v1/executions/{execution}"))
               )["state"] in ("queued", "running"):
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_POLL_S)
        if state["state"] != "succeeded":
            code = (state.get("error") or {}).get("code", "")
            raise TemporalUnavailable(f"TemporalDB execution {state['state']} {code}".strip())
        rows: list[dict] = []
        cursor = None
        while True:
            page = _json(await client.get(f"/temporal/v1/executions/{execution}/pages",
                                          params={"cursor": cursor} if cursor else None))
            if page.get("codec") != "arrow-json-v1" or not page["complete"] or page["truncated"]:
                raise TemporalUnavailable("TemporalDB result incomplete")
            rows += page["rows"]
            cursor = page["next_cursor"]
            if cursor is None:
                return rows
