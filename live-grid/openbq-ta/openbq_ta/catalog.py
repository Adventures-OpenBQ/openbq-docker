# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""One catalog projection and definition identity for every engine consumer."""

from dataclasses import fields
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import CodeType


@lru_cache(maxsize=1)
def _engine_digest():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _implementation(fn, seen=None):
    seen = set() if seen is None else seen
    if fn is None:
        return None
    if id(fn) in seen:
        return "<recursive>"
    seen.add(id(fn))
    code = getattr(fn, "__code__", None)

    def constant(value):
        if isinstance(value, CodeType):
            return {
                "code": value.co_code.hex(),
                "consts": [constant(v) for v in value.co_consts],
                "names": value.co_names,
            }
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [constant(v) for v in value]
        if isinstance(value, dict):
            return {str(k): constant(v) for k, v in value.items()}
        return type(value).__name__

    return {
        "code": constant(code) if code else type(fn).__name__,
        "defaults": constant(getattr(fn, "__defaults__", None)),
        "closure": [
            _implementation(c.cell_contents, seen)
            if callable(c.cell_contents)
            else constant(c.cell_contents)
            for c in (getattr(fn, "__closure__", None) or ())
        ],
    }


def entry(ind):
    omitted = {"deps", "build", "iterate", "session_agg", "eodhd"}
    # A detached projection: editors cannot mutate shared defaults or another card.
    result = {f.name: getattr(ind, f.name) for f in fields(ind) if f.name not in omitted}
    result = json.loads(json.dumps(result, allow_nan=False))
    identity = {
        "metadata": result,
        "engine": _engine_digest(),
        "implementation": {
            name: _implementation(getattr(ind, name))
            for name in ("deps", "build", "iterate", "session_agg")
        },
    }
    result["definition_version"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result
