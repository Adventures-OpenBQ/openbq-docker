# Copyright 2026 SecretoftheUniverse.com LLC.
# SPDX-License-Identifier: Apache-2.0
"""Known bar boundary only: legacy unmarked timestamps mean UTC, never local.

Internal study clocks remain naive UTC. This is not a generic parser for arbitrary
provider/local wall times. The current frame representation supports microseconds;
unsupported precision is rejected rather than silently truncated.
"""
from datetime import date, datetime, time, timezone
import re

_ISO = re.compile(
    r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?', re.I)


def _parsed(value) -> datetime:
    if isinstance(value, datetime):
        if getattr(value, 'nanosecond', 0):
            raise ValueError('bar timestamp precision exceeds microseconds')
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if not isinstance(value, str) or not _ISO.fullmatch(value.strip()):
        raise ValueError('ISO bar date or timestamp required (microsecond precision)')
    # datetime.fromisoformat accepts overflowing offset minutes; the wire does not.
    offset = re.search(r'[+-](\d{2}):?(\d{2})$', value.strip())
    if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
        raise ValueError('invalid bar timestamp offset')
    return datetime.fromisoformat(value.strip().replace('z', 'Z').replace('Z', '+00:00'))


def naive_utc(value) -> datetime:
    """Normalize a known bar instant, keeping the engine's naive-UTC clock."""
    point = _parsed(value)
    return (point.astimezone(timezone.utc).replace(tzinfo=None)
            if point.tzinfo is not None else point)


def wire_time(value, *, date_only=False) -> str | None:
    """Explicit UTC instant, or unchanged market-date label when date-only."""
    if value is None:
        return None
    point = _parsed(value)
    if date_only or (isinstance(value, date) and not isinstance(value, datetime)) or (
            isinstance(value, str) and len(value.strip()) == 10):
        return point.date().isoformat()
    return naive_utc(point).replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
