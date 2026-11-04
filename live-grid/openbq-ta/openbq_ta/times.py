# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Time values on the wire (spec 2026-11-04 §2): an ISO-8601 instant, or OBS-n.

Every other expression (`T-1bd@open`, `now-1h`, ...) is the host's to resolve before it
calls either service. OBS-n is a fact about the trade tape, so only a service holding the
trades can answer it.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone

from openbq_ta.registry import StudyError

_OBS = re.compile(r"OBS-([1-9][0-9]{0,6})")


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)


def _instant(text: str) -> datetime:
    return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))


def resolve_time(value, trades: Sequence[datetime | str] = ()) -> datetime:
    """`value` as an aware UTC datetime. A naive instant is UTC. `OBS-n` is the timestamp of
    the n-th most recent trade in `trades`, which is newest first. Anything else raises
    StudyError."""
    if isinstance(value, datetime):
        return _utc(value)
    text = str(value).strip()
    match = _OBS.fullmatch(text)
    if match:
        n = int(match.group(1))
        if n > len(trades):
            raise StudyError(f"{text}: only {len(trades)} trades held")
        at = trades[n - 1]
        return _utc(at) if isinstance(at, datetime) else _instant(str(at))
    try:
        return _instant(text)
    except ValueError:
        raise StudyError(f"{text!r} is not an ISO-8601 instant or OBS-n;"
                         f" the host resolves expressions") from None
