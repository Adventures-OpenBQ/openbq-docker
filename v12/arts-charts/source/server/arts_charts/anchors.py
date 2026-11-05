# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Time values Art's Charts reads (spec 2026-11-04 §2, S4, S14).

On the wire: an ISO-8601 instant, or OBS-n. In a chart document: each expression is
stored with the instant the host resolved it to on save, {"expr": ..., "at": ...}. The
server reads only `at`. A legacy entry holding only an expression has no instant, so it
reads as unresolvable until the host saves the document again. The grammar lives in the
host, not here.
"""
from __future__ import annotations

import re
from datetime import datetime

_OBS = re.compile(r"OBS-[1-9][0-9]{0,6}")


def is_anchor(text) -> bool:
    if not isinstance(text, str):
        return False
    text = text.strip()
    if _OBS.fullmatch(text):
        return True
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def instant(value) -> str | None:
    """What the server reads from a stored time value: the instant, OBS-n, or None."""
    if isinstance(value, dict):
        at = value.get("at") if set(value) == {"expr", "at"} else None
        return at if is_anchor(at) and not _OBS.fullmatch(at.strip()) else None
    return value if is_anchor(value) else None


def is_time_value(value) -> bool:
    """A stored time value: a literal, {expr, at} with a real instant, or a legacy
    expression-only text (stored as written, read as unresolvable)."""
    if isinstance(value, dict):
        expr = value.get("expr")
        return isinstance(expr, str) and 0 < len(expr) <= 64 and instant(value) is not None
    return isinstance(value, str) and 0 < len(value) <= 64
