# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""v1 interchange, validation and canonical content identity."""

from datetime import date, datetime, timedelta
from typing import Literal, Annotated
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .canonical import bundle_digest

MAX_DAYS = 366 * 20
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def instant(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("canonical UTC timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("aware UTC timestamp required")
    return parsed


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Segment(ClosedModel):
    start: str
    end: str

    @model_validator(mode="after")
    def ordered(self):
        if instant(self.start) >= instant(self.end):
            raise ValueError("segment end must follow start")
        return self


class Evidence(ClosedModel):
    id: str
    kind: Literal[
        "library",
        "religious_notice",
        "government_notice",
        "exchange_notice",
        "exchange_conditional_resolution",
        "central_bank_notice",
        "payment_operator_notice",
        "clearing_notice",
    ]
    domain: Literal["observance", "trading", "settlement"]
    references: list[str]


class Candidate(ClosedModel):
    id: str
    condition: str
    evidenceReferences: list[str]


class CalendarDay(ClosedModel):
    date: str
    state: Literal["open", "closed", "unresolved"]
    evidenceStatus: Literal[
        "library_baseline", "provisional", "authority_confirmed", "market_final", "operator_final", "conflict"
    ]
    open: str | None
    close: str | None
    segments: list[Segment]
    evidence: list[Evidence]
    candidates: list[Candidate]
    selectedBranch: str | None

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("ISO date required")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.state == "open":
            if not self.open or not self.close or not self.segments:
                raise ValueError("open session needs segments")
            if self.segments[0].start != self.open or self.segments[-1].end != self.close:
                raise ValueError("session boundary mismatch")
            if any(instant(a.end) > instant(b.start) for a, b in zip(self.segments, self.segments[1:])):
                raise ValueError("overlapping segments")
        elif self.open or self.close or self.segments:
            raise ValueError("non-open day has session")
        if self.evidenceStatus == "market_final" and not any(
            e.domain == "trading" and e.kind in {"exchange_notice", "exchange_conditional_resolution"} and e.references
            for e in self.evidence
        ):
            raise ValueError("exchange evidence required for market_final")
        if self.evidenceStatus == "operator_final" and not any(
            e.domain == "settlement"
            and e.kind in {"central_bank_notice", "payment_operator_notice", "clearing_notice"}
            and e.references
            for e in self.evidence
        ):
            raise ValueError("settlement authority evidence required")
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids) or self.selectedBranch is not None and self.selectedBranch not in ids:
            raise ValueError("invalid branch membership")
        return self


class Coverage(ClosedModel):
    start: str
    end: str
    complete: bool

    @model_validator(mode="after")
    def bounded(self):
        start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        if start.isoformat() != self.start or end.isoformat() != self.end or not 0 <= (end - start).days < MAX_DAYS:
            raise ValueError("invalid coverage range")
        return self


class Source(ClosedModel):
    adapter: str
    packageVersion: str
    tzdataVersion: str
    ruleDigest: Digest


class CalendarBundle(ClosedModel):
    schemaVersion: Literal[1]
    # The library's own names include 24/5, 24/7 and us_futures (2026-10-24 full calendar set).
    calendarId: Annotated[str, Field(pattern=r"^(exchange|payment|settlement):[A-Za-z0-9_/-]+$")]
    name: str
    kind: Literal["exchange_trading", "currency_payment", "securities_settlement"]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    timezone: str
    definitionRevision: str
    aliasRevision: str
    resolverPolicyVersion: Literal["calendar-v1"]
    generatedAt: str
    coverage: Coverage
    source: Source
    days: list[CalendarDay]
    digest: Digest

    @model_validator(mode="after")
    def consistent(self):
        ZoneInfo(self.timezone)
        instant(self.generatedAt)
        prefix = {
            "exchange_trading": "exchange:",
            "currency_payment": "payment:",
            "securities_settlement": "settlement:",
        }[self.kind]
        if not self.calendarId.startswith(prefix) or self.kind == "currency_payment" and not self.currency:
            raise ValueError("calendar kind/identity/currency mismatch")
        if len(self.days) > MAX_DAYS:
            raise ValueError("day limit")
        start, end = date.fromisoformat(self.coverage.start), date.fromisoformat(self.coverage.end)
        labels = [d.date for d in self.days]
        if labels != sorted(set(labels)) or any(not self.coverage.start <= d <= self.coverage.end for d in labels):
            raise ValueError("invalid day labels")
        if self.coverage.complete and labels != [
            (start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)
        ]:
            raise ValueError("incomplete claimed coverage")
        if self.digest != bundle_digest(self.model_dump(mode="json")):
            raise ValueError("bundle digest mismatch")
        return self


def validate_bundle(value):
    return CalendarBundle.model_validate(value).model_dump(mode="json")
