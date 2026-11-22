"""Authenticated bounded chart-stream-v1 endpoint, independent of legacy sockets."""

import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
import secrets
import time

from fastapi import WebSocket, WebSocketDisconnect
from .auth import auth_enabled, credentials_ok
from .chart_stream_protocol import validate, normalize_view, view_key, cursor_cmp, wire
from .chart_stream_pump import ChartPump, SharedChartSource

CONNECTION_BYTES = 8 * 1024 * 1024
PROCESS_BYTES = 128 * 1024 * 1024
# Two bounded native responses (16 MiB) plus the shared completed cache (8 MiB).
SOURCE_RESERVE = 24 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
CONTROL_RESERVE = 16 * 1024
MAX_CONNECTIONS = 64
SEND_SECONDS = 5
PROGRESS_SECONDS = 15
POLL_SECONDS = 0.05


class Overloaded(Exception):
    pass


class ChartService:
    def __init__(self, source):
        self.source = SharedChartSource(source) if source else None
        self.connections = 0
        self.pending_bytes = 0

    async def endpoint(self, ws: WebSocket):
        # This new surface is never anonymous, even when legacy auth is disabled.
        if (
            not auth_enabled()
            or not credentials_ok(ws.headers.get("authorization"))
            or not self.source
            or not getattr(self.source, "qualified", False)
        ):
            await ws.close(code=1008)
            return
        if self.connections >= MAX_CONNECTIONS:
            await ws.close(code=4009)
            return
        self.connections += 1
        connection = Connection(self, ws)
        try:
            await ws.accept()
            await connection.run()
        finally:
            await connection.cleanup()
            self.connections -= 1


class Connection:
    def __init__(self, service, ws):
        self.service, self.ws = service, ws
        self.queue = asyncio.Queue(maxsize=100)
        self.subscriptions = {}
        self.pending = []
        self.bytes = 0
        self.tasks = set()
        self.controls = deque()
        self.closed = False

    def release(self, entry):
        if entry["released"]:
            return
        if entry.get("sending"):
            entry["release_after_send"] = True
            return
        entry["released"] = True
        entry["text"] = ""
        self.bytes -= entry["size"]
        self.service.pending_bytes -= entry["size"]

    def discard(self, sid):
        for entry in self.pending:
            if entry["sid"] == sid:
                self.release(entry)
        self.pending = [e for e in self.pending if not e["released"]]

    def enqueue(self, frame, cursor=None, control=False):
        validate(frame)
        text = json.dumps(frame, separators=(",", ":"), allow_nan=False)
        size = len(text.encode())
        ceiling = CONNECTION_BYTES if control else CONNECTION_BYTES - CONTROL_RESERVE
        if (
            self.bytes + size > ceiling
            or self.service.pending_bytes + size > PROCESS_BYTES - SOURCE_RESERVE
            or len(self.pending) >= (100 if control else 96)
            or self.queue.full()
        ):
            raise Overloaded()
        entry = dict(
            sid=frame["subscription_id"],
            generation=frame["generation"],
            cursor=cursor,
            size=size,
            text=text,
            sent=False,
            created=time.monotonic(),
            released=False,
        )
        self.bytes += size
        self.service.pending_bytes += size
        self.pending.append(entry)
        self.queue.put_nowait(entry)

    def frame(self, sub, kind, **fields):
        return dict(
            protocol_version=1,
            type=kind,
            subscription_id=sub["sid"],
            generation=sub["generation"],
            **fields,
        )

    async def reset(self, sub, reason, status=None):
        sub["active"] = False
        self.discard(sub["sid"])
        try:
            status = wire(
                status or await asyncio.wait_for(self.service.source.status(), SEND_SECONDS)
            )
            self.enqueue(
                self.frame(
                    sub,
                    "resync_required",
                    reason=reason,
                    current_cursor=status["current_cursor"],
                    coverage=status["coverage"],
                ),
                control=True,
            )
        except Exception:
            # A reset is useful only if it can be delivered within the same bounds.
            await self.ws.close(code=4009)
            self.closed = True

    async def sender(self):
        while True:
            entry = await self.queue.get()
            if entry["released"]:
                continue
            entry["sending"] = True
            try:
                await asyncio.wait_for(self.ws.send_text(entry["text"]), SEND_SECONDS)
            finally:
                entry["sending"] = False
            entry["sent"] = True
            if entry["cursor"] is None or entry.get("release_after_send"):
                self.release(entry)
            self.pending = [e for e in self.pending if not e["released"]]

    def changes(self, sub, data):
        if "reason" in data:
            return False
        fields = {k: data[k] for k in ("from_cursor", "through_cursor")}
        kind = sub["view"]["mode"]
        if kind == "ticks":
            batches = []
            for batch in data["batches"]:
                ticks = [
                    tick
                    for tick in batch["ticks"]
                    if (tick["time"], int(tick["tick_id"]["seq"]))
                    >= (sub["floor"]["time"], int(sub["floor"].get("seq") or 0))
                ]
                if ticks:
                    batches.append(dict(batch, ticks=ticks))
            fields["batches"] = batches
        else:
            candles = [
                c
                for c in data["candles"]
                if c["key"]["bucket_start"] >= sub["floor"]["bucket_start"]
            ]
            keys = {json.dumps(k, sort_keys=True): k for k in sub["keys"]}
            for candle in candles:
                keys[json.dumps(candle["key"], sort_keys=True)] = candle["key"]
            sub["keys"] = sorted(keys.values(), key=lambda k: k["bucket_start"])[
                -sub["view"]["max_items"] :
            ]
            if len(keys) > len(sub["keys"]):
                sub["floor"] = {"kind": "candle", "bucket_start": sub["keys"][0]["bucket_start"]}
            fields["candles"] = [
                c for c in candles if c["key"]["bucket_start"] >= sub["floor"]["bucket_start"]
            ]
        self.enqueue(self.frame(sub, kind, **fields), cursor=data["through_cursor"])
        sub["high"] = data["through_cursor"]
        return True

    async def statuses(self, sub, keys):
        if not keys:
            return []
        status = wire(await asyncio.wait_for(self.service.source.status(), SEND_SECONDS))
        clock = status["clock"]
        intervals = {"1s": 1, "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}

        def closed(key):
            dt = datetime.fromisoformat(key["bucket_start"].replace("Z", "+00:00"))
            end = dt + timedelta(seconds=intervals[key["interval"]])
            return end <= datetime.fromisoformat(clock.replace("Z", "+00:00"))

        return [dict(key=key, status="closed" if closed(key) else "open") for key in keys]

    async def produce(self, sub, checkpoint):
        pump = ChartPump(self.service.source, sub["view"])
        try:
            if checkpoint:
                pump.cursor = checkpoint["cursor"]
                pump.floor = checkpoint["view_floor"]
                if checkpoint["view_key"] != view_key(sub["view"]):
                    return await self.reset(sub, "view_mismatch")
                floor = checkpoint["view_floor"]
                field = "time" if sub["view"]["mode"] == "ticks" else "bucket_start"
                earliest = sub["view"]["start"]
                if field == "bucket_start":
                    seconds = {
                        "1s": 1,
                        "1m": 60,
                        "5m": 300,
                        "15m": 900,
                        "30m": 1800,
                        "1h": 3600,
                        "1d": 86400,
                    }[sub["view"]["interval"]]
                    start = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                    bucket = int(start.timestamp() // seconds) * seconds
                    earliest = datetime.fromtimestamp(bucket, timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S.000000000Z"
                    )
                if (
                    floor["kind"] != ("tick" if field == "time" else "candle")
                    or floor[field] < earliest
                ):
                    return await self.reset(sub, "view_mismatch")
                if (
                    field == "time"
                    and floor["seq"] is not None
                    and int(floor["seq"]) > int(checkpoint["cursor"]["seq"])
                ) or ("end" in sub["view"] and floor[field] >= sub["view"]["end"]):
                    return await self.reset(sub, "view_mismatch")
                sub["floor"] = floor
                keys = checkpoint.get("retained_candle_keys", [])
                if sub["view"]["mode"] == "candles" and "retained_candle_keys" not in checkpoint:
                    return await self.reset(sub, "view_mismatch")
                if any(
                    k["symbol"] != sub["view"]["symbol"]
                    or k["interval"] != sub["view"].get("interval")
                    or k["bucket_start"] < floor[field]
                    for k in keys
                ):
                    return await self.reset(sub, "view_mismatch")
                initial = await pump.poll()
                if "reason" in initial:
                    return await self.reset(sub, initial["reason"], initial)
                sub["high"] = checkpoint["cursor"]
                sub["keys"] = keys
                baseline = await self.statuses(sub, keys)
                sub["statuses"] = baseline
                self.enqueue(
                    self.frame(
                        sub,
                        "resumed",
                        cursor=checkpoint["cursor"],
                        view=sub["view"],
                        view_key=view_key(sub["view"]),
                        view_floor=floor,
                        status_seq="0",
                        statuses=baseline,
                    ),
                    cursor=checkpoint["cursor"],
                )
            else:
                snapshot, initial = await pump.admit()
                if "reason" in initial:
                    return await self.reset(sub, initial["reason"], initial)
                sub["floor"] = snapshot["view_floor"]
                items = snapshot["items"]
                if len(items) > sub["view"]["max_items"]:
                    raise ValueError("snapshot cap")
                sub["keys"] = [i["key"] for i in items] if sub["view"]["mode"] == "candles" else []
                sub["statuses"] = (
                    [dict(key=i["key"], status=i["status"]) for i in items] if sub["keys"] else []
                )
                sub["high"] = snapshot["cursor"]
                begin = self.frame(
                    sub,
                    "snapshot_begin",
                    view=sub["view"],
                    view_key=view_key(sub["view"]),
                    **{k: snapshot[k] for k in ("view_floor", "cursor", "coverage", "truncated")},
                    item_count=str(len(items)),
                )
                frames = [begin]
                chunk = []
                for item in items:
                    candidate = self.frame(
                        sub,
                        "snapshot_chunk",
                        chunk_index=str(len(frames) - 1),
                        items=chunk + [item],
                    )
                    if len(json.dumps(candidate, separators=(",", ":")).encode()) > CHUNK_BYTES:
                        if not chunk:
                            raise Overloaded()
                        frames.append(
                            self.frame(
                                sub, "snapshot_chunk", chunk_index=str(len(frames) - 1), items=chunk
                            )
                        )
                        chunk = [item]
                    else:
                        chunk.append(item)
                if chunk:
                    frames.append(
                        self.frame(
                            sub, "snapshot_chunk", chunk_index=str(len(frames) - 1), items=chunk
                        )
                    )
                frames.append(
                    self.frame(
                        sub,
                        "snapshot_end",
                        cursor=snapshot["cursor"],
                        chunk_count=str(len(frames) - 1),
                        item_count=str(len(items)),
                    )
                )
                for frame in frames:
                    self.enqueue(frame, cursor=snapshot["cursor"])
            if cursor_cmp(initial["through_cursor"], sub["high"]) > 0:
                self.changes(sub, initial)
                pump.floor = sub["floor"]
            last_heartbeat = time.monotonic()
            while sub["active"] and not self.closed:
                await asyncio.sleep(POLL_SECONDS)
                if not auth_enabled() or not credentials_ok(self.ws.headers.get("authorization")):
                    await self.ws.close(code=1008)
                    self.closed = True
                    return
                now = time.monotonic()
                if now - sub["alive"] > PROGRESS_SECONDS or any(
                    e["sid"] == sub["sid"] and e["cursor"] and now - e["created"] > PROGRESS_SECONDS
                    for e in self.pending
                ):
                    return await self.reset(sub, "slow_consumer")
                data = await pump.poll()
                if "reason" in data:
                    return await self.reset(sub, data["reason"], data)
                if cursor_cmp(data["through_cursor"], sub["high"]) > 0:
                    self.changes(sub, data)
                    pump.floor = sub["floor"]
                if sub["keys"]:
                    statuses = await self.statuses(sub, sub["keys"])
                    if statuses != sub["statuses"]:
                        sub["status_seq"] += 1
                        self.enqueue(
                            self.frame(
                                sub,
                                "candle_status",
                                status_seq=str(sub["status_seq"]),
                                statuses=statuses,
                            )
                        )
                        sub["statuses"] = statuses
                if now - last_heartbeat >= 5:
                    self.enqueue(
                        self.frame(sub, "heartbeat", high_cursor=sub["high"]), control=True
                    )
                    last_heartbeat = now
        except Overloaded:
            await self.reset(sub, "slow_consumer")
        except Exception:
            await self.ws.close(code=1011)
            self.closed = True

    async def receive(self):
        while not self.closed:
            text = await asyncio.wait_for(
                self.ws.receive_text(), PROGRESS_SECONDS if not self.subscriptions else None
            )
            now = time.monotonic()
            while self.controls and self.controls[0] <= now - 1:
                self.controls.popleft()
            self.controls.append(now)
            if len(text.encode()) > 65536 or len(self.controls) > 10:
                raise ValueError("control limit")
            frame = json.loads(text)
            if frame.get("type") in ("subscribe", "resume"):
                frame["view"] = normalize_view(frame["view"])
            validate(frame)
            sid, kind = frame["subscription_id"], frame["type"]
            if kind in ("subscribe", "resume"):
                if sid in self.subscriptions or len(self.subscriptions) >= 8:
                    raise ValueError("subscription limit")
                sub = dict(
                    sid=sid,
                    generation=secrets.token_hex(16),
                    view=frame["view"],
                    high=None,
                    alive=now,
                    active=True,
                    status_seq=0,
                    keys=[],
                    statuses=[],
                )
                self.subscriptions[sid] = sub
                task = asyncio.create_task(self.produce(sub, frame.get("checkpoint")))
                sub["task"] = task
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            else:
                sub = self.subscriptions.get(sid)
                if not sub or frame.get("generation") != sub["generation"]:
                    raise ValueError("stale generation")
                if kind == "ack":
                    cursor = frame["cursor"]
                    if sub.get("last_ack") is not None and cursor_cmp(cursor, sub["last_ack"]) < 0:
                        raise ValueError("ack went backwards")
                    if not sub["high"] or cursor_cmp(cursor, sub["high"]) > 0:
                        raise ValueError("ack ahead")
                    eligible = [
                        e
                        for e in self.pending
                        if e["sid"] == sid and e["cursor"] and cursor_cmp(e["cursor"], cursor) <= 0
                    ]
                    if any(not e["sent"] for e in eligible):
                        raise ValueError("ack before send")
                    for entry in eligible:
                        self.release(entry)
                    self.pending = [e for e in self.pending if not e["released"]]
                    sub["last_ack"] = cursor
                    sub["alive"] = now
                elif kind == "pong":
                    sub["alive"] = now
                elif kind == "unsubscribe":
                    sub["active"] = False
                    sub["task"].cancel()
                    self.discard(sid)
                    self.enqueue(self.frame(sub, "unsubscribed"), control=True)
                    del self.subscriptions[sid]
                else:
                    raise ValueError("server frame from client")

    async def run(self):
        sender = asyncio.create_task(self.sender())
        receiver = asyncio.create_task(self.receive())
        self.tasks.update((sender, receiver))
        try:
            done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError):
            pass
        except (ValueError, TypeError, KeyError):
            await self.ws.close(code=1008)
        except (TimeoutError, Overloaded):
            await self.ws.close(code=4009)

    async def cleanup(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        for task in list(self.tasks):
            with suppress(asyncio.CancelledError, Exception):
                await task
        for entry in self.pending:
            self.release(entry)
        self.pending.clear()


def attach_chart_stream(app, source):
    service = ChartService(source)
    app.state.chart_stream = service
    app.websocket("/chart_stream_ws")(service.endpoint)
    return service
