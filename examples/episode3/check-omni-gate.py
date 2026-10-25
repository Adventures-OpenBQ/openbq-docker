#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Build-time gate: with OPENBQ_OMNI_EXEC_ALLOWED unset, no Omni code may run.

Run from the app directory. Imports the real app and POSTs a harmless body to
each code-executing Omni route straight into the ASGI app, in process (nothing
goes over the network). Each must answer 403; exits non-zero (failing `docker
build`) otherwise, e.g. if upstream renames a route so the gate no longer
matches it.
"""
import asyncio
import os
import sys

os.environ.pop("OPENBQ_OMNI_EXEC_ALLOWED", None)
sys.path.insert(0, ".")
from reference_app import app, CODE_EXECUTING_OMNI  # noqa: E402


async def post_status(path: str) -> int:
    body = b'{"prompt": "x = 1"}'
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 0), "server": ("localhost", 80),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


problems = []
for path in CODE_EXECUTING_OMNI:
    status = asyncio.run(post_status(path))
    if status != 403:
        problems.append(f"POST {path} answered {status} with nothing allowed, expected 403")
# Each gated path must be a served route, or the gate guards nothing.
os.environ["OPENBQ_OMNI_EXEC_ALLOWED"] = ",".join(CODE_EXECUTING_OMNI.values())
for path in CODE_EXECUTING_OMNI:
    status = asyncio.run(post_status(path))
    if status in (404, 405):
        problems.append(f"POST {path} answered {status} when allowed; update CODE_EXECUTING_OMNI")
os.environ.pop("OPENBQ_OMNI_EXEC_ALLOWED")

if problems:
    raise SystemExit("check-omni-gate: FAILED\n  " + "\n  ".join(problems))
print(f"check-omni-gate: {', '.join(sorted(CODE_EXECUTING_OMNI))} refused with nothing allowed")
