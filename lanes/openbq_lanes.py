# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Run heavy OpenBB routes in a worker process the API can kill (OpenBQ D8).

CFTC and FINRA bond routes do CPU-bound work and build 40-400 MB responses.
In the API process that holds the GIL and the server loop, so /widgets.json
and every other route stall behind them, and nothing can stop a synchronous
pandas section. Here they run in one long-lived child process, the "heavy"
lane: the same openbb-api app, served on a Unix socket. This middleware
forwards the raw request to it and copies the response back; the API only
waits on a socket.

- One request at a time; the rest queue, up to OPENBQ_LANE_QUEUE_MAX, else 503.
- Past OPENBQ_LANE_DEADLINE seconds (queue wait included) the lane is killed,
  the request gets 504, and the lane is respawned. A worker still starting is
  never killed; the request gets 503 instead, unless it has been starting for
  over OPENBQ_LANE_STARTUP_LIMIT seconds (180), when it is replaced.
- A lane over OPENBQ_LANE_RSS_MB after a call is restarted while idle.
- A response over OPENBQ_MAX_RESULT_BYTES is refused with 413.
- OPENBQ_ISOLATE lists the path prefixes; set it empty to run everything in
  process as before.

Hooked in through openbb.toml ``[middleware] hooks``; the worker loads the
same hook with OPENBQ_ROLE=worker and passes everything through.
"""

import asyncio
import atexit
import base64
import glob
import json
import logging
import os
import secrets
import subprocess
import sys
import time

import httpx
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

log = logging.getLogger("uvicorn.error")

DEFAULT_ISOLATE = "/api/v1/cftc/,/api/v1/finra/fixedincome/bonds"
# Fixed for the life of the process, yet rebuilt per request upstream: ~5 MB
# of widgets JSON serialized on the server loop, and apps.json does that again
# and then awaits 32 provider apps endpoints on their provider loops (TMX's
# waits behind covered_calls). Under CPU contention each probe took seconds.
# ponytail: edits to workspace_apps.json or widget settings need a restart.
_CATALOGS = {"/widgets.json", "/apps.json"}
# BDOBB's own example dashboards. They use BDOBB built-in cards (note, clock,
# markdown), which openbb-api's /apps.json drops because no backend widget has
# those ids, so they are appended to the built catalog as shipped.
EXTRA_APPS = os.environ.get("OPENBQ_EXTRA_APPS", "/workspace/bdobb_apps.json")
# Cards BDOBB draws itself (its src/lib/builtins.ts, v3 through v10): no
# backend serves them, so they never appear in /widgets.json.
BUILTIN_CARDS = frozenset({
    "note", "markdown", "website", "clock", "rss", "news", "date_probe", "param_echo",
    "period_echo", "local_table", "linked_table", "linked_chart",
})
# BDOBB's logo, the img of the served examples. Workspace fetches app images
# without credentials, so this one path answers without Basic auth.
LOGO_PATH = "/openbq/bdobb-logo.svg"
LOGO_FILE = os.environ.get("OPENBQ_BDOBB_LOGO", "/workspace/bdobb-logo.svg")
# The response's own framing; the API sets its own.
_HOP = {b"content-length", b"transfer-encoding", b"connection", b"keep-alive"}
# Per-caller CORS answers: never cached, _cors() recomputes them per request.
_PER_CALLER = {b"vary"}


def _rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _apps(body: bytes):
    """(apps, extended): the built apps.json list, plus EXTRA_APPS when that is a list too.
    (None, False) when the build is not a JSON list."""
    try:
        apps = json.loads(body)
    except ValueError:
        return None, False
    if not isinstance(apps, list):
        return None, False
    try:
        with open(EXTRA_APPS, encoding="utf-8") as f:
            extra = json.load(f)
    except (OSError, ValueError):
        return apps, False
    return (apps + extra, True) if isinstance(extra, list) else (apps, False)


def _cards(app) -> set:
    """The widget ids of an app's cards, over every tab."""
    tabs = app.get("tabs") if isinstance(app, dict) else None
    if not isinstance(tabs, dict):
        return set()
    return {card.get("i") for tab in tabs.values() if isinstance(tab, dict)
            for card in tab.get("layout") or [] if isinstance(card, dict)}


def _servable_apps(apps: list, widget_ids) -> list:
    """Drop every app with a card that is neither in /widgets.json nor a BDOBB built-in.

    A provider that is not installed would otherwise ship its apps as blank
    cards: openbb-api keeps an app when any one of its tabs resolves.
    """
    kept = []
    for app in apps:
        missing = sorted(map(str, _cards(app) - BUILTIN_CARDS - widget_ids))
        if missing:
            log.warning("OpenBQ apps.json: dropped app %r: no widget in /widgets.json for %s",
                        app.get("name"), ", ".join(missing))
        else:
            kept.append(app)
    return kept


async def _widget_ids(cache, request):
    """The ids /widgets.json serves, from the catalog cache (built through the app if need be)."""
    if "/widgets.json" not in cache:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://openbq") as client:
            await client.get("/widgets.json")  # through this hook, which caches it
    if "/widgets.json" not in cache:
        return None
    try:
        widgets = json.loads(cache["/widgets.json"][0])
    except ValueError:
        return None
    return set(widgets) if isinstance(widgets, dict) else None


def _logo(request):
    """BDOBB's logo, without credentials (Workspace fetches app images without them)."""
    try:
        with open(LOGO_FILE, "rb") as f:
            svg = f.read()
    except OSError:
        return _cors(request, JSONResponse({"detail": "Not Found"}, 404))
    return _cors(request, Response(svg, 200, media_type="image/svg+xml",
                                   headers={"Cache-Control": "public, max-age=86400"}))


def _is_catalog(request) -> bool:
    return request.method == "GET" and request.url.path in _CATALOGS and not request.url.query


async def _catalog(cache, request, call_next):
    """Serve /widgets.json and /apps.json from their first successful build."""
    if not _authorized(request):  # the cache must not outlive the API's own Basic auth
        return _unauthorized(request)
    path = request.url.path
    if path not in cache:
        response = await call_next(request)
        if response.status_code != 200:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if path == "/apps.json":
            apps, extended = _apps(body)
            if extended:
                body = json.dumps(apps).encode()
            if apps is not None and any(_cards(app) - BUILTIN_CARDS for app in apps):
                widget_ids = await _widget_ids(cache, request)
                if widget_ids is None:  # no widget catalog yet: serve as built, cache nothing
                    log.warning("OpenBQ apps.json: /widgets.json unavailable, apps not checked")
                    return _cors(request, Response(body, 200, media_type="application/json"))
                kept = _servable_apps(apps, widget_ids)
                if len(kept) < len(apps):
                    body = json.dumps(kept).encode()
        cache[path] = (body, [
            (k, v) for k, v in response.raw_headers
            if k.lower() not in _HOP | _PER_CALLER and not k.lower().startswith(b"access-control-")
        ])
    body, headers = cache[path]
    response = Response(body, 200)
    response.raw_headers = [*headers, (b"content-length", str(len(body)).encode())]
    return _cors(request, response)


def _unauthorized(request):
    return _cors(request, JSONResponse({"detail": "Unauthorized"}, 401, {"WWW-Authenticate": "Basic"}))


def _cors(request, response):
    """openbb-api adds [middleware] hooks outside its CORSMiddleware, so answers made here pass through it."""
    for entry in getattr(request.app, "user_middleware", []):
        if entry.cls is CORSMiddleware:
            return CORSMiddleware(response, *entry.args, **entry.kwargs)
    return response


def _authorized(request) -> bool:
    """The status endpoint follows the API's Basic auth when it is on."""
    if os.environ.get("OPENBB_API_AUTH", "").lower() not in ("1", "true", "yes"):
        return True
    expected = f"{os.environ.get('OPENBB_API_USERNAME', '')}:{os.environ.get('OPENBB_API_PASSWORD', '')}"
    given = request.headers.get("authorization", "")
    return secrets.compare_digest(
        given.encode(), b"Basic " + base64.b64encode(expected.encode())
    )


class Lane:
    """One worker process serving the allowlisted routes one request at a time."""

    def __init__(self, command, socket, prefixes, deadline=165.0, queue_max=16,
                 rss_mb=3584.0, max_bytes=256 << 20, shard_dir=None, name="heavy",
                 startup_limit=180.0):
        self.command, self.socket, self.prefixes = command, socket, prefixes
        self.deadline, self.queue_max, self.rss_mb = deadline, queue_max, rss_mb
        self.max_bytes, self.shard_dir, self.name = max_bytes, shard_dir, name
        self.startup_limit = startup_limit
        self.spawned_at = 0.0
        self.proc = None
        self.lock = asyncio.Lock()
        self.waiting = 0
        self.restarts = 0
        self.last_kill = None
        self._client = None
        self._monitor = None
        self._ready_pid = None
        self.catalogs = {}

    # -- process -----------------------------------------------------------

    def start(self):
        """Spawn the worker. Its own startup (the platform import) is awaited per request."""
        if self.shard_dir:  # temp files of a killed writer (openbb_cftc/utils/store.py)
            for orphan in glob.glob(os.path.join(self.shard_dir, "*.tmp*")):
                os.remove(orphan)
        if os.path.exists(self.socket):
            os.remove(self.socket)
        os.makedirs(os.path.dirname(self.socket), exist_ok=True)
        self.proc = subprocess.Popen(self.command, env={**os.environ, "OPENBQ_ROLE": "worker"})
        self.spawned_at = time.monotonic()
        log.info("OpenBQ lane %s: worker pid %s starting", self.name, self.proc.pid)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    async def _restart(self, reason: str):
        """Kill and respawn off the server loop: reaping a worker stuck in I/O can block."""
        self.last_kill = {"reason": reason, "pid": self.proc.pid if self.proc else None, "at": time.time()}
        self.restarts += 1
        await asyncio.get_running_loop().run_in_executor(None, lambda: (self.stop(), self.start()))

    async def _ready(self):
        """Wait until the worker accepts connections (any HTTP answer will do)."""
        while self._ready_pid != self.proc.pid:
            if self.proc.poll() is not None:
                raise httpx.ConnectError("lane worker exited during startup")
            try:
                await self._http().get("/openbq/ready", timeout=5)
                self._ready_pid = self.proc.pid
            except httpx.TransportError:
                await asyncio.sleep(0.2)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=self.socket), base_url="http://lane", timeout=None
            )
        return self._client

    def status(self) -> dict:
        alive = self.proc is not None and self.proc.poll() is None
        return {self.name: {
            "pid": self.proc.pid if alive else None,
            "rss_mb": round(_rss_mb(self.proc.pid), 1) if alive else None,
            "busy": self.lock.locked(), "queued": self.waiting,
            "restarts": self.restarts, "last_kill": self.last_kill,
        }}

    # -- requests ----------------------------------------------------------

    async def handle(self, request, call_next):
        if self._monitor is None:
            self._monitor = asyncio.ensure_future(_watch_loop_lag())
        path = request.url.path
        if path == "/openbq/lanes":
            if not _authorized(request):
                return _unauthorized(request)
            return _cors(request, JSONResponse(self.status()))
        if _is_catalog(request):
            return await _catalog(self.catalogs, request, call_next)
        if (request.method == "OPTIONS" or path.endswith("_choices")
                or not any(path.startswith(p) for p in self.prefixes)):
            return await call_next(request)

        body = await request.body()
        until = time.monotonic() + self.deadline
        if self.waiting >= self.queue_max:
            return self._answer(503, "The heavy-route lane's queue is full.", request, "queue-503")
        self.waiting += 1
        try:
            await asyncio.wait_for(self.lock.acquire(), self.deadline)
        except TimeoutError:
            return self._answer(503, "The heavy-route lane stayed busy past this request's deadline.",
                                request, "queue-503")
        finally:
            self.waiting -= 1
        # Shielded: a client that gives up does not cancel the call, so the
        # lane is never handed a second request while the first still runs.
        return await asyncio.shield(asyncio.ensure_future(self._run(request, body, until)))

    async def _run(self, request, body, until):
        queued = time.monotonic() - (until - self.deadline)
        started, outcome, size, status = time.monotonic(), "ok", 0, 0
        try:
            if self.proc is None or self.proc.poll() is not None:
                await self._restart("worker exited")
            elif (self._ready_pid != self.proc.pid
                  and time.monotonic() - self.spawned_at > self.startup_limit):
                await self._restart(f"not started within {self.startup_limit:g} s")
            try:
                status, headers, data = await asyncio.wait_for(
                    self._exchange(request, body), until - time.monotonic()
                )
            except TimeoutError:
                if self._ready_pid != self.proc.pid:
                    # Still importing the platform (~30 s): killing it would only
                    # start that over, and every later request would time out too.
                    outcome = "starting-503"
                    return self._error(request, 503, "The heavy-route worker is still starting.")
                outcome = "killed-504"
                await self._restart("deadline")
                return self._error(request, 504, f"The request did not finish within {self.deadline:g} seconds.")
            except httpx.TransportError:
                outcome = "died-502"
                await self._restart("worker died")
                return self._error(request, 502, "The heavy-route worker died during the request; it has been restarted.")
            if data is None:
                outcome = "too-large-413"
                return self._error(request, 413, f"The result is larger than {self.max_bytes} bytes.")
            size = len(data)
            response = Response(data, status)
            response.raw_headers = [h for h in headers if h[0].lower() not in _HOP]
            response.raw_headers.append((b"content-length", str(size).encode()))
            return response
        finally:
            try:
                pid = self.proc.pid if self.proc else None
                rss = _rss_mb(pid) if pid else 0.0
                log.info(
                    "OpenBQ lane %s: %s %s status=%s outcome=%s queue_ms=%d run_ms=%d bytes=%d pid=%s rss_mb=%.0f",
                    self.name, request.method, request.url.path, status, outcome,
                    queued * 1000, (time.monotonic() - started) * 1000, size, pid, rss,
                )
                if outcome == "ok" and rss > self.rss_mb:
                    await self._restart(f"rss {rss:.0f} MB over {self.rss_mb:g} MB")
            finally:
                self.lock.release()

    async def _exchange(self, request, body):
        """Send the raw request to the worker; return (status, headers, body or None if too large)."""
        await self._ready()
        headers = [(k, v) for k, v in request.headers.raw if k.lower() not in _HOP]
        if b"accept-encoding" not in (k.lower() for k, _ in headers):
            headers.append((b"accept-encoding", b"identity"))  # not httpx's own gzip default
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        async with self._http().stream(request.method, url, headers=headers, content=body) as response:
            if int(response.headers.get("content-length", 0)) > self.max_bytes:
                return response.status_code, [], None
            chunks, size = [], 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > self.max_bytes:
                    return response.status_code, [], None
                chunks.append(chunk)
            return response.status_code, response.headers.raw, b"".join(chunks)

    def _error(self, request, status, detail):
        headers = {"Retry-After": "30"} if status == 503 else None
        return _cors(request, JSONResponse({"detail": detail}, status, headers))

    def _answer(self, status, detail, request, outcome):
        log.info("OpenBQ lane %s: %s %s status=%s outcome=%s", self.name, request.method,
                 request.url.path, status, outcome)
        return self._error(request, status, detail)


async def _watch_loop_lag(interval=0.1, threshold=0.25):
    """Log any server-loop pause over 250 ms: the wedge alarm."""
    while True:
        before = time.monotonic()
        await asyncio.sleep(interval)
        lag = time.monotonic() - before - interval
        if lag > threshold:
            log.warning("OpenBQ loop lag: the server loop paused %.2f s", lag)


def _shard_dir():
    try:
        from openbb_core.app.utils import get_user_cache_directory

        return os.path.join(get_user_cache_directory(), "cftc", "dtcc", "record_shards")
    except Exception:  # noqa: BLE001  no cache directory, nothing to sweep
        return None


LANE = None
_CATALOG_CACHE = {}  # used when no lane is configured (OPENBQ_ISOLATE empty)
_prefixes = [p for p in os.environ.get("OPENBQ_ISOLATE", DEFAULT_ISOLATE).split(",") if p.strip()]
if os.environ.get("OPENBQ_ROLE") != "worker" and _prefixes:
    _socket = os.environ.get("OPENBQ_LANE_SOCKET", "/run/openbq/heavy.sock")
    LANE = Lane(
        [os.path.join(os.path.dirname(sys.executable), "openbb-api"), "--uds", _socket],
        _socket,
        [p.strip() for p in _prefixes],
        deadline=float(os.environ.get("OPENBQ_LANE_DEADLINE", 165)),
        queue_max=int(os.environ.get("OPENBQ_LANE_QUEUE_MAX", 16)),
        rss_mb=float(os.environ.get("OPENBQ_LANE_RSS_MB", 3584)),
        max_bytes=int(os.environ.get("OPENBQ_MAX_RESULT_BYTES", 256 << 20)),
        shard_dir=_shard_dir(),
        startup_limit=float(os.environ.get("OPENBQ_LANE_STARTUP_LIMIT", 180)),
    )
    LANE.start()  # eagerly: its platform import overlaps the API's own
    atexit.register(LANE.stop)


PROVIDERS_PATH = "/providers.json"
_OPTIONAL = frozenset({"cftc", "econdb"})  # bls is key-required
_LOCAL = frozenset({"deltalake", "kdb"})
_NAMES = {
    "yfinance": "Yahoo Finance", "sec": "SEC", "federal_reserve": "Federal Reserve",
    "imf": "IMF", "oecd": "OECD", "government_us": "US Government", "fmp": "FMP",
    "fred": "FRED", "tiingo": "Tiingo", "eia": "EIA", "bls": "BLS", "cftc": "CFTC",
    "congress_gov": "Congress.gov", "econdb": "EconDB", "intrinio": "Intrinio",
    "benzinga": "Benzinga", "tradingeconomics": "TradingEconomics", "eodhd": "EODHD",
    "deltalake": "Delta Lake", "kdb": "kdb+",
}


def provider_descriptor(credentials: dict) -> list:
    """key-maint's provider inventory (Episode 3): which providers this API has
    and which credential names each takes. Names only; no value is read.
    Unit-tested in key-maint/tests/test_providers_route.py."""
    out = []
    for pid in sorted(credentials):
        names = list(credentials[pid])
        auth = ("optional" if pid in _OPTIONAL else "required") if names else "not_required"
        out.append({"id": pid, "name": _NAMES.get(pid, pid.replace("_", " ").title()),
                    "credentials": names, "env_vars": [c.upper() for c in names],
                    "auth": auth, "local": pid in _LOCAL})
    return out


def _provider_credentials() -> dict:
    from openbb_core.app.provider_interface import ProviderInterface  # the API process only
    return ProviderInterface().credentials


async def middleware(request, call_next):
    """openbb.toml [middleware] hook."""
    if request.url.path == LOGO_PATH and request.method in ("GET", "HEAD"):
        return _logo(request)
    if request.method == "GET" and request.url.path == PROVIDERS_PATH:
        if not _authorized(request):
            return _unauthorized(request)
        return _cors(request, JSONResponse(provider_descriptor(_provider_credentials())))
    if LANE is not None:
        return await LANE.handle(request, call_next)
    if _is_catalog(request):  # with the lane off, the catalogs keep their cache and BDOBB examples
        return await _catalog(_CATALOG_CACHE, request, call_next)
    return await call_next(request)
