# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version
from hashlib import sha256
from pathlib import Path
import exchange_calendars as xc
import pandas as pd
from .canonical import bundle_digest, canonical_bytes
from .contracts import Coverage, validate_bundle
from .registry import bounds, resolve_calendar


def utc(value):
    return value.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_bundle(calendar_id: str, start: date, end: date, *, generated_at: datetime):
    name = resolve_calendar(calendar_id)
    low, high = bounds(name)
    if start < low:
        raise ValueError(f"historical {name} sessions before {low.isoformat()} are unqualified")
    if end > high:
        raise ValueError(f"{name} is served to {high.isoformat()}")
    Coverage(start=start.isoformat(), end=end.isoformat(), complete=True)
    if generated_at.utcoffset() is None:
        raise ValueError("aware generation time required")
    # Construct whole years, clipped to the served bounds: the library refuses a range past its own (XSHG starts
    # 1990-12-03, XSES ends 2026-12-31), and our public contract also supports one closed day or a closed-only range.
    first, last = max(date(start.year, 1, 1), low), min(date(end.year, 12, 31), high)
    cal = xc.get_calendar(name, start=first.isoformat(), end=last.isoformat())
    schedule = cal.schedule.loc[start.isoformat() : end.isoformat()]
    sessions = {idx.date(): row for idx, row in schedule.iterrows()}
    days = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        row = sessions.get(day)
        out = {
            "date": day.isoformat(),
            "state": "closed",
            "evidenceStatus": "library_baseline",
            "open": None,
            "close": None,
            "segments": [],
            "evidence": [],
            "candidates": [],
            "selectedBranch": None,
        }
        if row is not None:
            opening, closing = utc(row["open"]), utc(row["close"])
            segments = [{"start": opening, "end": closing}]
            if pd.notna(row["break_start"]) and pd.notna(row["break_end"]):
                segments = [
                    {"start": opening, "end": utc(row["break_start"])},
                    {"start": utc(row["break_end"]), "end": closing},
                ]
            out.update(state="open", open=opening, close=closing, segments=segments)
        days.append(out)
    # Hash the actual supplier Python source, not just its package version label.
    root = Path(xc.__file__).parent
    inventory = {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.py"))}
    source = {
        "adapter": "openbq-calendar/0.1.0",
        "packageVersion": version("exchange_calendars"),
        "tzdataVersion": version("tzdata"),
        "ruleDigest": sha256(canonical_bytes(inventory)).hexdigest(),
    }
    b = {
        "schemaVersion": 1,
        "calendarId": "exchange:" + name,
        "name": name,
        "kind": "exchange_trading",
        "currency": None,
        "timezone": str(cal.tz),
        "definitionRevision": "registry-v1",
        "aliasRevision": "registry-v1",
        "resolverPolicyVersion": "calendar-v1",
        "generatedAt": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage": {"start": start.isoformat(), "end": end.isoformat(), "complete": True},
        "source": source,
        "days": days,
        "digest": "0" * 64,
    }
    b["digest"] = bundle_digest(b)
    return validate_bundle(b)
