# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""A stand-in lane worker: the same kinds of routes as the heavy ones, served on a Unix socket."""
import asyncio
import os
import sys
import time

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI()
_hoard = []


@app.api_route("/api/v1/cftc/echo", methods=["GET", "POST"])
async def echo(request: Request):
    return {"pid": os.getpid(), "query": str(request.url.query),
            "body": (await request.body()).decode(), "x-test": request.headers.get("x-test"),
            "accept-encoding": request.headers.get("accept-encoding")}


@app.get("/api/v1/cftc/rows")
async def rows():
    return {"results": [{"pid": os.getpid()}]}


@app.get("/api/v1/cftc/spin")
def spin(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:  # synchronous CPU work: nothing can interrupt it
        pass
    return {"spun": seconds}


@app.get("/api/v1/cftc/sleep")
async def sleep(seconds: float):
    await asyncio.sleep(seconds)
    return {"slept": seconds, "pid": os.getpid()}


@app.get("/api/v1/cftc/big")
async def big(n: int):
    return Response(b"x" * n, media_type="application/octet-stream")


@app.get("/api/v1/cftc/hog")
async def hog(mb: int):
    _hoard.append(bytearray(mb << 20))
    return {"pid": os.getpid()}


if __name__ == "__main__":
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)  # the platform import, standing in
    uvicorn.run(app, uds=sys.argv[1], log_level="warning")
