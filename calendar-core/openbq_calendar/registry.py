# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The calendars openbq-docker serves: exactly resources/calendar-catalogue.json, which catalogue.py generates.

A name is resolved, never guessed. The catalogue lists each calendar's library aliases (NYSE, XNAS, …) for reference
only; they are not served under those names (ruling RF3).
"""

import json
from datetime import date

from .catalogue import PATH

ENTRIES = {entry["mic"]: entry for entry in json.loads(PATH.read_bytes())["calendars"]}
CALENDARS = tuple(ENTRIES)


def resolve_calendar(identifier):
    if not isinstance(identifier, str):
        raise ValueError("unknown calendar")
    name = identifier.removeprefix("exchange:")
    if name not in CALENDARS:
        raise ValueError("unknown or unqualified calendar")
    return name


def bounds(name):
    """The first and last date served for a calendar, as the catalogue measured them inside 1990..2040."""
    served = ENTRIES[name]["bounds"]
    return date.fromisoformat(served["start"]), date.fromisoformat(served["end"])
