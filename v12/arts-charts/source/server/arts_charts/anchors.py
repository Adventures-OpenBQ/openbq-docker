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
#: The client's LITERAL (chartDocument.ts): extended ISO dates and instants only. Basic
#: (20260101) and week (2026-W01-1) forms are expressions there, so they are not here.
_LITERAL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9:.]+(Z|[+-][0-9]{2}:?[0-9]{2})?)?")


def is_anchor(text) -> bool:
    if not isinstance(text, str):
        return False
    text = text.strip()
    if _OBS.fullmatch(text):
        return True
    if not _LITERAL.fullmatch(text):
        return False
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


def fixed_range(body: dict) -> tuple[str, str] | None:
    """(start, end) dates of a saved range both of whose ends are literal instants -- a
    window the user fixed. None for a relative range (stored {expr, at}, S14), an OBS-n end
    or no range."""
    window = body.get("range") or {}
    ends = [window.get("from"), window.get("to")]
    if all(isinstance(e, str) and instant(e) and not e.strip().startswith("OBS-") for e in ends):
        return ends[0].strip()[:10], ends[1].strip()[:10]
    return None
