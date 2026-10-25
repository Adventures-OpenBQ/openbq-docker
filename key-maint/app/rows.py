# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Assemble widget rows from parsed credentials, applying tier redaction.

`value` is ABSENT (not masked) below tier 3, so no client rendering bug can
ever leak it. `values=None` means the file was unreadable: emit a banner row
plus one 'unknown' row per registered provider — HTTP 200 always."""
from __future__ import annotations

from app.probes import WORST_RANK
from app.registry import (
    IGNORE,
    LOCAL_PROVIDERS,
    OPTIONAL_PROVIDERS,
    PROVIDERS,
    is_demo,
    provider_index,
)

_CRED_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")

_NOT_INSTALLED = {
    "result": "skipped",
    "detail": "not installed on this backend",
    "kind": "connectivity",
    "code": "not_installed",
}


def _status(values: dict[str, str], env_var: str) -> str:
    if env_var not in values:
        return "missing"
    return "set" if values[env_var] else "empty"


def _row(name: str, env_var: str, values: dict[str, str], tier: int, **extra) -> dict:
    """A credential row; the value itself only at tier 3."""
    row = {"provider": name, "env_var": env_var, "status": _status(values, env_var),
           "demo": is_demo(env_var, values.get(env_var, "")), **extra}
    if tier == 3 and env_var in values:
        row["value"] = values[env_var]
    return row


def worst_check(checks: list[dict]) -> dict | None:
    """The worst check by result rank: no_response > error > auth_failed >
    skipped > ok. None when there are no checks."""
    if not checks:
        return None
    return max(checks, key=lambda c: WORST_RANK.get(c.get("result", "ok"), 0))


def _attach_checks(row: dict, tests, provider_id: str) -> None:
    checks = (tests or {}).get(provider_id)
    if checks:
        row["checks"] = list(checks)
        row["test"] = worst_check(checks)


def build_rows(
    values: dict[str, str] | None,
    tier: int,
    tests: dict[str, list[dict]] | None,
    *,
    malformed: list[str] | None = None,
    descriptor: list[dict] | None = None,
) -> list[dict]:
    if values is None:
        banner = {
            "provider": "⚠ credentials.env",
            "env_var": "",
            "status": "unknown",
            "demo": False,
        }
        unknowns = [
            {"provider": p.name, "env_var": var, "status": "unknown", "demo": False}
            for var, p in PROVIDERS.items()
        ]
        return [banner, *unknowns]

    if descriptor is None:
        rows = _registry_only_rows(values, tier, tests)
    else:
        rows = _joined_rows(values, tier, tests, descriptor)

    # Credential-shaped vars present in the file but unknown to the registry.
    for var in values:
        if var in PROVIDERS or var in IGNORE or not var.endswith(_CRED_SUFFIXES):
            continue
        rows.append(_row(var, var, values, tier))

    if malformed:
        rows.extend(
            {
                "provider": "⚠ malformed line",
                "env_var": entry,
                "status": "unknown",
                "demo": False,
            }
            for entry in malformed
        )
    return rows


def _registry_only_rows(values, tier, tests):
    """Descriptor unavailable: today's rows plus provider_id and registry
    auth. No `supported` key at all -- the descriptor never spoke, so
    "supported" cannot be answered, not even as `supported: None`."""
    rows = []
    for var, p in PROVIDERS.items():
        # Registry entries are all credentialed; the optional set is the exception.
        auth = "optional" if p.provider_id in OPTIONAL_PROVIDERS else "required"
        row = _row(p.name, var, values, tier, provider_id=p.provider_id, auth=auth)
        _attach_checks(row, tests, p.provider_id)
        rows.append(row)
    return rows


def _joined_rows(values, tier, tests, descriptor):
    """Join the live descriptor against the local registry. Descriptor-named
    non-local providers come first, in descriptor order (Cases A/B below),
    then registry entries the descriptor did not name (Case C/D)."""
    idx = provider_index()  # provider_id -> Provider
    rows = []
    named: set[str] = set()
    for d in descriptor:
        pid = d.get("id")
        if not pid or d.get("local") or pid in LOCAL_PROVIDERS:
            continue
        named.add(pid)
        auth = d.get("auth", "unknown")
        p = idx.get(pid)
        if p is not None:
            # Case A: descriptor provider WITH a registry entry.
            row = _row(p.name, p.env_var, values, tier, provider_id=pid, auth=auth, supported=True)
        else:
            # Case B: descriptor provider WITHOUT a registry entry
            #         (keyless, or a keyed provider the registry has not learned).
            #         A keyless provider's row never carries a value.
            env_vars = d.get("env_vars") or []
            env_var = env_vars[0] if env_vars else ""
            keyless = auth == "not_required"
            row = _row(d.get("name") or pid.replace("_", " ").title(), env_var, values,
                       0 if keyless else tier, provider_id=pid, auth=auth, supported=True)
        _attach_checks(row, tests, pid)
        rows.append(row)

    # Case D: registry entries the descriptor did not name -> not installed.
    for var, p in PROVIDERS.items():
        if p.provider_id in named:
            continue
        row = _row(p.name, var, values, tier, provider_id=p.provider_id, auth="required",
                   supported=False, test=dict(_NOT_INSTALLED), checks=[dict(_NOT_INSTALLED)])
        rows.append(row)  # no probe attempted; fixed skipped test overrides any supplied check
    return rows


def build_summary(rows: list[dict], *, descriptor_available: bool = True) -> str:
    """Key state as markdown, for the summary widget.

    Counts and provider names only, deliberately. Tier-3 rows carry the
    credential itself in row["value"]; this must never render it, which is
    also why its widget declares no raw view.
    """
    lines = []
    if not descriptor_available:
        lines += ["Provider inventory unavailable; showing configured credentials only.", ""]

    by_status: dict[str, list[str]] = {}
    for row in rows:
        by_status.setdefault(str(row.get("status", "unknown")), []).append(
            str(row.get("provider", "?"))
        )
    total = len(rows)
    n_set = len(by_status.get("set", []))
    lines += [f"**{n_set} of {total} provider keys configured**", ""]
    for status, label in (
        ("missing", "Missing"),
        ("empty", "Present but empty"),
        ("unknown", "Unreadable"),
    ):
        names = sorted(by_status.get(status, []))
        if names:
            lines.append(f"- **{label} ({len(names)}):** {', '.join(names)}")
    demo = sorted(str(r.get("provider", "?")) for r in rows if r.get("demo"))
    if demo:
        lines.append(
            f"- **Public demo key ({len(demo)}):** {', '.join(demo)}"
            " -- rate-limited and shared; replace before relying on it."
        )
    if n_set == total and not demo:
        lines.append("- Every provider is configured with a private key.")
    return "\n".join(lines)
